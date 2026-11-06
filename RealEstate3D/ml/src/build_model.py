"""Оценка зданий Саратова под склад: признаки → обучение и проверка моделей → балл → зоны → отчёты.

Запуск (из папки ml):
    python src/build_model.py            полный расчёт (≈ 10–15 мин)
    python src/build_model.py --fast     без подбора гиперпараметров (≈ 3 мин)
    python src/build_model.py --test     только часть города (проверка, что всё работает)
    python src/build_model.py --refresh  пересчёт итогов и зон после правки конфига (без обучения, ≈ 1 мин)
Потом:  python src/make_map.py ;  python src/make_notebook.py

Результаты: ml/out/ (Excel, отчёт, карта, SQLite), ml/models/warehouse_model.joblib.
Функции для объявлений: building_report(osm_id | адрес), score_address(адрес) — см. внизу файла.
"""
import json, math, os, pickle, sys, time
from collections import Counter

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F                                  # noqa: E402
import osm_data as od                                 # noqa: E402
import scoring as sc                                  # noqa: E402
import train_model as tm                              # noqa: E402
from paths import CONFIG, DATA, DE_SQLITE, ML, MODELS, OUT   # noqa: E402
from truck_network import TruckNetwork                # noqa: E402

RESULTS = DATA / "buildings_scored.pkl"   # всё, что нужно building_report и карте
EXPERT_XLSX = ML / "labels" / "expert_labels.xlsx"
log = tm.log


# сколько знаков после запятой хранится в карте (остальные признаки — 3 знака)
MAP_DECIMALS = {**{"t_" + k: 1 for k in F.EXIT_KEY.values()}, "t_best": 1, "t_backup": 1, "lm_len_m": 0,
                "lm_yard_m": 0, "lm_turns": 0, "lm_narrow_m": 0, "lm_oneway_n": 0, "d_truck_road_m": 0,
                "d_closed_road_gap_m": 0, "restr_dist_m": 0, "res_n_100": 0, "res_n_200": 0, "res_n_500": 0,
                "d_school_m": 0, "d_hospital_m": 0, "d_rail_m": 0, "d_rail_station_m": 0, "city_center_min": 1,
                "city_mean_min": 1, "lm_time_min": 1, "d_center_km": 2}


def load_config():
    return json.load(open(CONFIG, encoding="utf-8"))


def pct_function(ref):
    """Перцентиль «лучше, чем X% зданий города» по отсортированным прогнозам модели (OOF)."""
    srt = np.sort(ref)

    def pct(p):
        return 100.0 * np.searchsorted(srt, p, side="left") / len(srt)
    return pct


# ---------------------------------------------------------------- основной расчёт
def main(fast=False, test=False):
    cfg = load_config()
    t0 = time.time()
    np.random.seed(cfg["random_state"])
    log("граф для фур (база дата-инженера)…")
    net = TruckNetwork(DE_SQLITE)
    log(f"  рёбер {net.E}, участков {len(net.pieces)}, закрыто для фур дорог {len(net.why_blocked)}")
    city = od.load_city()
    industrial = od.load_industrial(city)
    b = od.load_buildings(city)
    b = F.city_buildings(b, industrial, cfg)
    if test:   # проверка на части города: север (Вольский тракт, Солнечный) — там есть и склады, и жильё
        b = b[(b["lat"] > 51.58) & (b["lon"] < 46.02)].reset_index(drop=True)
    osm = {"industrial": industrial, "res_landuse": od.load_residential_landuse(), "rail": od.load_rail(),
           "poi": od.load_poi()}
    X, side, extra = F.build_features(net, b, osm, cfg)

    # ---------------- метки и модели
    labels = tm.make_labels(b, side, cfg)
    groups = tm.spatial_blocks(b, cfg["model"]["block_km"])
    log(f"метка A: {labels['A'].sum()} складов/производств из {len(b)} зданий; "
        f"метка B: те же против {int((labels['B'] == 0).sum())} жилых домов")
    log("обучение и проверка, вариант A…")
    met_a, oof_a, models_a, chosen_a, folds = tm.evaluate_models(X, labels, groups, cfg, "A", fast=fast or test)
    log("обучение и проверка, вариант B…")
    met_b, oof_b, models_b, chosen_b, _ = tm.evaluate_models(X, labels, groups, cfg, "B", fast=fast or test)
    metrics = pd.concat([met_a, met_b], ignore_index=True)
    summary = tm.summarize(metrics)
    sa = summary[summary.variant == "A"].set_index("model")
    best_any = sa["ap"].idxmax()
    # итоговая модель — с монотонными ограничениями, если она не хуже лучшей больше чем на 3% AP:
    # так балл гарантированно не растёт от «плохих» признаков (защита от бессмысленных зависимостей)
    final = "hgb_mono" if sa.loc["hgb_mono", "ap"] >= 0.97 * sa.loc[best_any, "ap"] else best_any
    log(f"лучшая по AP: {best_any}; итоговая: {final}")
    y = labels["A"]
    oof = oof_a[final]
    fmodels = models_a[final]
    cal = tm.cross_calibrate(oof, y, folds)
    calib = tm.calibration_table(cal, y)
    calib_raw_brier = float(np.mean((oof - y) ** 2))
    calib_brier = float(np.mean((cal - y) ** 2))
    pct = pct_function(oof)
    ml = np.round(pct(oof), 1)

    # монотонность: время до СКАД −5 мин не снижает балл (проверка на всех зданиях)
    mono_check = None
    if final != "formula":
        Xn = X[F.FEATURES].to_numpy(dtype=float)
        j = F.FEATURES.index("t_skad")
        worse = 0
        for m, (tr, te) in zip(fmodels, folds):
            Xp = Xn[te].copy()
            Xp[:, j] = np.maximum(Xp[:, j] - 5, 0)
            worse += int((m.predict_proba(Xp)[:, 1] < m.predict_proba(Xn[te])[:, 1] - 1e-12).sum())
        mono_check = {"зданий проверено": len(X), "балл снизился": worse}
        log(f"  проверка монотонности (СКАД −5 мин): балл снизился у {worse} зданий")

    # ---------------- исследование групп признаков и важность
    params = Counter(json.dumps(p, sort_keys=True) for p in chosen_a[final]).most_common(1)[0][0]
    params = json.loads(params)
    if final == "logreg":
        abl_kind = "logreg"
    else:
        abl_kind = final
    log("исследование по группам признаков…")
    abl = tm.ablation(X, labels, groups, cfg, abl_kind, params, folds)
    log("важность признаков…")
    imp = tm.permutation_groups(fmodels, folds, X, y, F.FEATURES, cfg["random_state"], repeats=1 if test else 2)
    contrib = tm.group_contributions(fmodels, folds, X, oof, F.FEATURES, pct).round(1)

    # ---------------- подбаллы, профили, правила
    wh = F.cluster_counts(b[["x", "y"]].to_numpy(), labels["positive"])
    subs = sc.subscores(X, b, wh["wh_n_1000"], cfg)
    mask = sc.rule_mask(X, b, side, cfg)

    # ---------------- экспертная разметка (если есть)
    expert = expert_stage(b, X, ml, subs, groups, cfg)
    ml_final = expert["ml"] if expert and expert.get("use") else ml

    totals = {}
    for p in cfg["profiles"]:
        totals[p] = np.array([sc.profile_score(ml_final[i], {k: subs[k][i] for k in sc.PROFILE_PARTS}, mask[i], p, cfg)
                              for i in range(len(b))])

    # ---------------- таблица зданий (единый источник для карты, Excel и building_report)
    R = pd.DataFrame({"osm_id": b["osm_id"], "lon": b["lon"], "lat": b["lat"], "addr": b["addr"], "name": b["name"],
                      "building": b["building"], "type_ru": b["type_ru"], "area_m2": b["area_m2"], "poly": b["poly"],
                      "x": b["x"], "y": b["y"], "label_A": y, "label_why": labels["why"],
                      "p_model": np.round(oof, 4), "p_calibrated": np.round(cal, 3), "ml": ml_final,
                      "ml_model": ml, "mask": mask, "snap_piece": side["snap_piece"],
                      "restr_reason": side["restr_reason"], "closed_reason": side["closed_reason"],
                      "street_near": nearest_street(net, side["snap_piece"])})
    for k in sc.PROFILE_PARTS:
        R["s_" + k] = subs[k]
    for p in cfg["profiles"]:
        R["total_" + p] = totals[p]          # без округления: карта считает так же и округляет при показе
    for g in F.FEATURE_GROUPS:
        R["c_" + g] = contrib[g].to_numpy()
    for f in F.FEATURES:   # точность как в карте — тексты карточки в Python и в карте совпадают
        R[f] = np.round(X[f].to_numpy(), MAP_DECIMALS.get(f, 3))
    R["wh_n_1000"] = wh["wh_n_1000"]
    for k in cfg["exits"]["names"]:
        R["path_" + F.EXIT_KEY[k]] = side["path_" + F.EXIT_KEY[k]].to_numpy()
    R["addr_full"] = [a if a else (f"рядом с {s}" if s else "адрес не найден") for a, s in zip(R["addr"], R["street_near"])]

    zones, zone_of = make_zones(R, cfg)
    R["zone"] = zone_of
    errors = model_errors(R, oof, y)
    candidates = expert_candidates(R, oof_a, groups, cfg)
    R["label_candidate"] = 0
    R.loc[candidates, "label_candidate"] = 1

    # ---------------- сохранение
    report = {
        "Дата расчёта": time.strftime("%Y-%m-%d %H:%M"), "База дорог": net.dataset_key,
        "Зданий оценено": int(len(R)), "Складов/производств (метка A)": int(y.sum()),
        "Жилых домов (отрицательные в B)": int((labels["B"] == 0).sum()),
        "Доля положительных": round(float(y.mean()), 4),
        "Проверка": f"GroupKFold, {cfg['model']['folds']} разбиений по блокам {cfg['model']['block_km']}×"
                    f"{cfg['model']['block_km']} км ({len(set(groups))} блоков)",
        "Подбор гиперпараметров": "нет (быстрый режим)" if (fast or test) else "внутри обучающих блоков",
        "Лучшая модель по AP": best_any, "Итоговая модель": final, "Параметры итоговой модели": params,
        "Монотонность (СКАД −5 мин)": mono_check,
        "Brier до калибровки": round(calib_raw_brier, 4), "Brier после калибровки": round(calib_brier, 4),
        "Экспертная разметка": expert["summary"] if expert else "нет файла expert_labels.xlsx — экспертной проверки нет",
        "alpha": cfg["alpha"],
    }
    state = {"cfg": cfg, "R": R, "zones": zones, "summary": summary, "metrics": metrics, "ablation": abl,
             "importance": imp, "calibration": calib, "errors": errors, "report": report,
             "exits": {k: {"lonlat": v["lonlat"], "gap_m": v["gap_m"]} for k, v in extra["exits"].items()}}
    pickle.dump(state, open(RESULTS, "wb"))
    import joblib
    joblib.dump({"final": final, "features": F.FEATURES, "fold_models": fmodels, "folds_blocks_km": cfg["model"]["block_km"],
                 "oof_sorted": np.sort(oof), "monotonic": F.MONOTONIC, "random_state": cfg["random_state"],
                 "full_model": tm.make_model(final if final != "formula" else "hgb_mono", params, cfg, F.FEATURES)
                 .fit(X[F.FEATURES].to_numpy(dtype=float), y)},
                MODELS / "warehouse_model.joblib")
    import reports
    reports.write_all(state)
    log(f"готово за {time.time() - t0:.0f} с: {OUT}")
    return state


def nearest_street(net, snap_piece):
    """Название ближайшей улицы (для «рядом с …»): сам участок или соседние с именем."""
    names = np.array([net.ways[p["way"]]["name"] or F.REF_NAMES.get(net.ways[p["way"]]["ref"] or "", "")
                      for p in net.pieces], dtype=object)
    from sklearn.neighbors import KDTree
    mid = np.array([F.to_xy(*p["coords"][len(p["coords"]) // 2]) for p in net.pieces])
    has = names != ""
    tree = KDTree(mid[has])
    out = []
    for p in snap_piece:
        if p < 0:
            out.append("")
        elif names[p]:
            out.append(names[p])
        else:
            _, i = tree.query([mid[p]], k=1)
            out.append(names[has][i[0, 0]])
    return out


# ---------------------------------------------------------------- зоны
def make_zones(R, cfg):
    z = cfg["zones"]
    cell = z["cell_m"]
    tot = R["total_" + cfg["default_profile"]].to_numpy()
    gx, gy = (R["x"] // cell).astype(int).to_numpy(), (R["y"] // cell).astype(int).to_numpy()
    good = tot >= z["zone_score"]
    cnt = Counter(zip(gx[good], gy[good]))
    gcells = {c for c, n in cnt.items() if n >= z["min_good"]}
    comp, zid, zone_cell = set(), 0, {}
    for start in sorted(gcells):
        if start in comp:
            continue
        zid += 1
        stack = [start]
        comp.add(start)
        zone_cell[start] = zid
        while stack:
            i, j = stack.pop()
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    n = (i + di, j + dj)
                    if n in gcells and n not in comp:
                        comp.add(n)
                        zone_cell[n] = zid
                        stack.append(n)
    zone_of = np.array([zone_cell.get((i, j), 0) for i, j in zip(gx, gy)])
    rows = []
    for k in range(1, zid + 1):
        idx = np.where(zone_of == k)[0]
        g = R.iloc[idx]
        nonres = g[~g["building"].isin(od.RES_TYPES)]
        best = g["total_" + cfg["default_profile"]].idxmax()
        top3 = g.nlargest(3, "total_" + cfg["default_profile"]).index.tolist()
        streets = [s for s, _ in Counter([s for s in g["street_near"] if s]).most_common(3)]
        cells = sorted({(i, j) for i, j in zip(gx[idx], gy[idx])})
        rows.append({"zone_tmp": k, "score": float(R.at[best, "total_" + cfg["default_profile"]]),
                     "mean_score": float(nonres["total_" + cfg["default_profile"]].mean() if len(nonres) else np.nan),
                     "n_suitable": int((g["total_" + cfg["default_profile"]] >= z["suitable_score"]).sum()),
                     "n_good": int((g["total_" + cfg["default_profile"]] >= z["good_score"]).sum()),
                     "n_buildings": len(g), "area_ha": len(cells) * cell * cell / 1e4, "streets": ", ".join(streets),
                     "best": int(best), "top3": [int(i) for i in top3],
                     "cells": [[int(i), int(j)] for i, j in cells]})
    zones = pd.DataFrame(rows)
    if len(zones):
        zones = zones.sort_values(["score", "n_good"], ascending=False).reset_index(drop=True)
        remap = {int(t): i + 1 for i, t in enumerate(zones["zone_tmp"])}
        zone_of = np.array([remap.get(int(v), 0) for v in zone_of])
        zones.index += 1
        zones = zones.drop(columns="zone_tmp")
    return zones, zone_of


# ---------------------------------------------------------------- ошибки модели
def model_errors(R, oof, y):
    cols = ["osm_id", "addr_full", "type_ru", "area_m2", "street_near", "p_model", "ml", "label_why",
            "t_best", "lm_yard_m", "res_n_200", "d_rail_m"]
    fp = R.assign(p=oof)[y == 0].nlargest(20, "p")[cols].copy()
    fp.insert(0, "ошибка", "ложное «отлично»: модель уверена, но склада по OSM нет")
    fn = R.assign(p=oof)[y == 1].nsmallest(20, "p")[cols].copy()
    fn.insert(0, "ошибка", "пропущенный склад: склад есть, а модель его не узнала")
    out = pd.concat([fp, fn], ignore_index=True)
    out["что это за место"] = [describe_place(r) for _, r in out.iterrows()]
    return out


def describe_place(r):
    bits = [r["type_ru"]]
    if r["res_n_200"] >= 20:
        bits.append("среди жилья")
    if r["d_rail_m"] < 500:
        bits.append("у ж/д")
    if r["lm_yard_m"] >= 300:
        bits.append("подъезд через жилые улицы")
    if r["t_best"] <= 12:
        bits.append("у выезда из города")
    elif r["t_best"] >= 30:
        bits.append("далеко от выездов")
    if r["label_why"]:
        bits.append(r["label_why"])
    return ", ".join(bits)


# ---------------------------------------------------------------- экспертная разметка
def expert_candidates(R, oof_by_model, groups, cfg):
    """150 зданий для разметки: половина «спорные» (балл около середины или модели не согласны),
    половина — разные баллы; не больше 6 зданий из одного блока 3×3 км. Только нежилые от 100 м²."""
    e = cfg["expert"]
    rs = np.random.default_rng(cfg["random_state"])
    ok = (~R["building"].isin(od.RES_TYPES)) & (R["area_m2"] >= 100) & (R["lm_has_path"] > 0)
    pct = lambda p: pd.Series(p).rank(pct=True).to_numpy() * 100
    disagree = np.abs(pct(oof_by_model["hgb_mono"]) - pct(oof_by_model["logreg"]))
    mid = 100 - 2 * np.abs(R["total_" + cfg["default_profile"]].to_numpy() - 50)
    dispute = np.maximum(disagree, mid)
    n_disp = int(e["n_candidates"] * e["disputed_share"])
    chosen, per_block = [], Counter()

    def take(order, n):
        for i in order:
            if len(chosen) >= n:
                break
            if not ok[i] or i in chosen or per_block[groups[i]] >= 6:
                continue
            chosen.append(i)
            per_block[groups[i]] += 1
    take(np.argsort(-dispute), n_disp)
    take(rs.permutation(len(R)), e["n_candidates"])
    return chosen


def expert_stage(b, X, ml, subs, groups, cfg):
    """Если есть labels/expert_labels.xlsx (≥ min_labels оценок): согласие модели с экспертами и дообучение."""
    if not EXPERT_XLSX.exists():
        return None
    from scipy.stats import spearmanr
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupKFold
    lab = pd.read_excel(EXPERT_XLSX)
    m = {"Хорошо": 2, "Средне": 1, "Плохо": 0}
    lab = lab[lab["оценка"].isin(m)]
    idx_of = {int(o): i for i, o in enumerate(b["osm_id"])}
    lab = lab[lab["osm_id"].map(lambda o: int(o) in idx_of)]
    n = len(lab)
    if n < cfg["expert"]["min_labels"]:
        return {"summary": f"в expert_labels.xlsx {n} оценок — меньше {cfg['expert']['min_labels']}, дообучение не делалось"}
    ii = lab["osm_id"].map(lambda o: idx_of[int(o)]).to_numpy()
    ye = lab["оценка"].map(m).to_numpy()
    Z = np.column_stack([ml] + [subs[k] for k in sc.PROFILE_PARTS]) / 100
    rho_model = spearmanr(ml[ii], ye).statistic
    pred = np.zeros(n)
    gk = GroupKFold(n_splits=min(5, len(set(groups[ii]))))
    for tr, te in gk.split(Z[ii], ye, groups[ii]):
        pred[te] = _ordinal_fit(Z[ii][tr], ye[tr], cfg).predict(Z[ii][te])
    rho_stack = spearmanr(pred, ye).statistic
    cls_model = np.digitize(ml[ii], [35, 55])        # 0 «плохо», 1 «средне», 2 «хорошо»
    cls_stack = np.digitize(pred, [35, 55])
    acc = lambda c: float(np.mean(c == ye))
    full = _ordinal_fit(Z[ii], ye, cfg)
    use = rho_stack > rho_model
    summary = {"оценок": int(n), "Спирмен: модель ↔ эксперты": round(float(rho_model), 3),
               "Спирмен: дообученная ↔ эксперты (проверка по блокам)": round(float(rho_stack), 3),
               "Точность по классам: модель": round(acc(cls_model), 3),
               "Точность по классам: дообученная": round(acc(cls_stack), 3),
               "Итог берётся из": "дообученной модели" if use else "исходной модели (дообученная не стала ближе к экспертам)"}
    return {"summary": summary, "use": use, "ml": np.round(full.predict(Z), 1)}


class _Ordinal:
    """Порядковая регрессия «Плохо < Средне < Хорошо» из двух логистических: P(≥Средне), P(≥Хорошо)."""

    def __init__(self, a, b):
        self.a, self.b = a, b

    def predict(self, Z):
        return 50 * (self.a.predict_proba(Z)[:, 1] + self.b.predict_proba(Z)[:, 1])


def _ordinal_fit(Z, y, cfg):
    from sklearn.linear_model import LogisticRegression
    mk = lambda t: LogisticRegression(C=1.0, max_iter=2000, random_state=cfg["random_state"]).fit(Z, (y >= t).astype(int)) \
        if 0 < (y >= t).sum() < len(y) else _Const(float((y >= t).mean()))
    return _Ordinal(mk(1), mk(2))


class _Const:
    def __init__(self, p):
        self.p = p

    def predict_proba(self, Z):
        return np.column_stack([np.full(len(Z), 1 - self.p), np.full(len(Z), self.p)])


# ---------------------------------------------------------------- карточка здания (как на карте)
_STATE = None


def _state():
    global _STATE
    if _STATE is None:
        _STATE = pickle.load(open(RESULTS, "rb"))
        R = _STATE["R"]
        from sklearn.neighbors import KDTree
        _STATE["tree"] = KDTree(R[["x", "y"]].to_numpy())
        _STATE["by_id"] = {int(o): i for i, o in enumerate(R["osm_id"])}
    return _STATE


def values_for(r, cfg):
    """Числа здания для текстов — те же поля, что в карте."""
    names = cfg["exits"]["names"]
    times = {k: (float(r["t_" + F.EXIT_KEY[k]]) if r["path_" + F.EXIT_KEY[k]] else None) for k in names}
    ok = sorted([k for k in names if times[k] is not None], key=lambda k: (times[k], names.index(k)))
    return {"best": ok[0] if ok else None, "backup": ok[1] if len(ok) > 1 else None,
            "t_best": times[ok[0]] if ok else None, "t_backup": times[ok[1]] if len(ok) > 1 else None,
            "has_path": bool(r["lm_has_path"]), "lm_len": float(r["lm_len_m"]), "lm_yard": float(r["lm_yard_m"]),
            "lm_turns": float(r["lm_turns"]), "res_n_100": float(r["res_n_100"]), "res_n_200": float(r["res_n_200"]),
            "res_share_200": float(r["res_share_200"]), "d_school": float(r["d_school_m"]),
            "city_center": float(r["city_center_min"]), "city_share_25": float(r["city_share_25"]),
            "city_mean": float(r["city_mean_min"]), "d_rail": float(r["d_rail_m"]), "free": float(r["free_share_30"]),
            "restr_d": float(r["restr_dist_m"]), "restr_reason": r["restr_reason"] or "",
            "dead_end": bool(r["lm_dead_end"]), "oneway": float(r["lm_oneway_n"]), "narrow": float(r["lm_narrow_m"]),
            "closed_gap": float(r["d_closed_road_gap_m"]), "closed_reason": r["closed_reason"] or "",
            "d_center": float(r["d_center_km"]), "mask": int(r["mask"]),
            "no_path_exits": [k for k in names if times[k] is None], "times": times}


def _card(i, profile=None):
    S = _state()
    cfg, R = S["cfg"], S["R"]
    profile = profile or cfg["default_profile"]
    r = R.iloc[i]
    v = values_for(r, cfg)
    contrib = {g: float(r["c_" + g]) for g in F.FEATURE_GROUPS}
    ex = sc.explain(v, contrib, cfg)
    total = sc.profile_score(float(r["ml"]), {k: float(r["s_" + k]) for k in sc.PROFILE_PARTS}, int(r["mask"]),
                             profile, cfg)
    bd = sc.badge(total, cfg)
    alt = _best_near(r["x"], r["y"], cfg["alternative_radius_km"] * 1000, profile, exclude=i, n=1)
    out = {"osm_id": int(r["osm_id"]), "Адрес": r["addr_full"], "Название": r["name"], "Тип здания": r["type_ru"],
           "Площадь, м²": int(r["area_m2"]), "Профиль": cfg["profiles"][profile]["name"],
           "Итог, из 100": sc.f0(total), "Оценка": bd["label"],
           "Лучше, чем % зданий города (модель)": sc.f0(float(r["ml"])),
           **{f"Подбалл: {sc.PART_RU[k]}": sc.f0(float(r["s_" + k])) for k in sc.PROFILE_PARTS},
           **{f"{k}, мин": (sc.f0(t) if t is not None else "нет пути") for k, t in v["times"].items()},
           "До центра города, мин": sc.f0(v["city_center"]), "Среднее до центров спроса, мин": sc.f0(v["city_mean"]),
           "Почему подходит": ex["pros"], "Что мешает": ex["cons"], "Предупреждения": ex["warnings"],
           "Сработавшее правило": ex["rules"],
           "Вклад групп признаков, пункты": {F.GROUP_RU[g]: contrib[g] for g in F.FEATURE_GROUPS},
           "lat": float(r["lat"]), "lon": float(r["lon"])}
    if alt and float(R.at[alt[0], "total_" + profile]) > total + 3:
        a = R.iloc[alt[0]]
        out["Лучше рядом (3 км)"] = {"Адрес": a["addr_full"], "Итог": sc.f0(float(a["total_" + profile])),
                                     "На сколько лучше": sc.f0(float(a["total_" + profile]) - total),
                                     "osm_id": int(a["osm_id"])}
    return out


def _best_near(x, y, radius, profile, exclude=-1, n=3):
    S = _state()
    R = S["R"]
    idx = S["tree"].query_radius([[x, y]], r=radius)[0]
    idx = [int(i) for i in idx if i != exclude]
    idx.sort(key=lambda i: (-float(R.at[i, "total_" + profile]), i))
    return idx[:n]


def building_report(key, profile=None):
    """Карточка здания (словарь): key — osm_id здания (число) или адрес (строка)."""
    S = _state()
    if isinstance(key, (int, np.integer)) or (isinstance(key, str) and key.lstrip("-").isdigit()):
        i = S["by_id"].get(int(key))
        if i is None:
            return {"ошибка": f"здания с osm_id {key} нет среди оценённых"}
        return _card(i, profile)
    return score_address(key, profile)


def point_report(lat, lon, profile=None, snap_m=0):
    """Точка на карте: здание под точкой (для адреса — ещё и в snap_m метрах), иначе «Здесь нет здания»
    и 3 лучших здания в радиусе 2 км (как клик мимо здания на карте)."""
    S = _state()
    cfg, R = S["cfg"], S["R"]
    profile = profile or cfg["default_profile"]
    x, y = F.to_xy(lon, lat)
    from shapely.geometry import Point, Polygon
    pt = Point(x, y)
    near = S["tree"].query_radius([[x, y]], r=300)[0]
    for i in sorted(near, key=lambda i: (R.at[i, "x"] - x) ** 2 + (R.at[i, "y"] - y) ** 2):
        pts = [F.to_xy(*c) for c in od.decode_poly(R.at[i, "poly"])]
        if len(pts) >= 4 and Polygon(pts).contains(pt):
            return _card(int(i), profile)
    d, i = S["tree"].query([[x, y]], k=1)
    if snap_m and d[0, 0] <= snap_m:
        return _card(int(i[0, 0]), profile)
    best = _best_near(x, y, cfg["no_building_radius_km"] * 1000, profile, n=3)
    return {"Здание": "Здесь нет здания", "Лучшие здания в радиусе 2 км": [
        {"Адрес": R.at[j, "addr_full"], "Итог": sc.f0(float(R.at[j, "total_" + profile])), "osm_id": int(R.at[j, "osm_id"]),
         "lat": float(R.at[j, "lat"]), "lon": float(R.at[j, "lon"])} for j in best]}


ABBR = [("улица", "ул"), ("ул.", "ул"), ("проспект", "пр-т"), ("просп.", "пр-т"), ("пр.", "пр-т"),
        ("переулок", "пер"), ("пер.", "пер"), ("проезд", "пр-д"), ("шоссе", "ш"), ("ш.", "ш"),
        ("площадь", "пл"), ("пл.", "пл"), ("тракт", "тр"), ("бульвар", "б-р"), ("набережная", "наб"),
        ("тупик", "туп"), ("дом", ""), ("д.", ""), ("г.", ""), ("город", ""), ("саратов", "")]


def norm_address(s):
    """Нормализация адреса — та же, что в поиске на карте (normAddr)."""
    s = s.lower().replace("ё", "е")
    for ch in ",.;\"«»()":
        s = s.replace(ch, " " if ch not in "." else ". ")
    words = []
    for w in s.split():
        for a, bb in ABBR:
            if w == a or w == a.rstrip("."):
                w = bb
                break
        if w:
            words.append(w)
    return " ".join(words)


def search_buildings(query, limit=8):
    S = _state()
    R = S["R"]
    if "addr_norm" not in S:
        S["addr_norm"] = [norm_address(a + " " + n) if (a or n) else "" for a, n in zip(R["addr"], R["name"])]
    q = norm_address(query).split()
    if not q:
        return []
    hits = []
    for i, a in enumerate(S["addr_norm"]):
        if a and all(any(t == w or (w.startswith(t) and not t.isdigit()) for w in a.split()) for t in q):
            hits.append(i)
    hits.sort(key=lambda i: (len(S["addr_norm"][i]), i))
    return hits[:limit]


NOMINATIM_CACHE = DATA / "nominatim_cache.json"
_last_nom = [0.0]


def nominatim(query):
    """Поиск адреса в Nominatim: User-Agent проекта, не чаще 1 запроса в секунду, кэш, рамка Саратова."""
    import urllib.parse, urllib.request
    cache = json.load(open(NOMINATIM_CACHE, encoding="utf-8")) if NOMINATIM_CACHE.exists() else {}
    if query in cache:
        return cache[query]
    wait = 1.1 - (time.time() - _last_nom[0])
    if wait > 0:
        time.sleep(wait)
    _last_nom[0] = time.time()
    url = ("https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": query + ", Саратов", "format": "jsonv2", "limit": 1, "accept-language": "ru",
         "viewbox": "45.75,51.72,46.20,51.40", "bounded": 1}))
    req = urllib.request.Request(url, headers={"User-Agent": od.USER_AGENT})
    try:
        res = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception as e:
        return {"error": str(e)}
    out = {"lat": float(res[0]["lat"]), "lon": float(res[0]["lon"]), "name": res[0].get("display_name", "")} if res else None
    cache[query] = out
    json.dump(cache, open(NOMINATIM_CACHE, "w", encoding="utf-8"), ensure_ascii=False)
    return out


def score_address(address, profile=None):
    """Адрес объявления → карточка здания (сначала адреса OSM, потом Nominatim и ближайшее здание в 50 м)."""
    hits = search_buildings(address, limit=1)
    if hits:
        out = _card(hits[0], profile)
        out["Как найдено"] = "адрес в OSM"
        return out
    nom = nominatim(address)
    if not nom or "error" in (nom or {}):
        return {"ошибка": "адрес не найден" + (f" ({nom['error']})" if nom and "error" in nom else "")}
    out = point_report(nom["lat"], nom["lon"], profile, snap_m=_state()["cfg"]["address_snap_m"])
    out["Как найдено"] = f"Nominatim: {nom['name']}"
    return out


def refresh():
    """Пересчёт итогов, зон и отчётов из сохранённых баллов модели — без переобучения.
    Нужен после изменения alpha, весов профилей, порогов правил или зон в warehouse_config.json."""
    S = pickle.load(open(RESULTS, "rb"))
    cfg = load_config()
    R = S["R"]
    for p in cfg["profiles"]:
        R["total_" + p] = [sc.profile_score(float(m), {k: float(R.at[i, "s_" + k]) for k in sc.PROFILE_PARTS},
                                            int(R.at[i, "mask"]), p, cfg) for i, m in enumerate(R["ml"])]
    zones, zone_of = make_zones(R, cfg)
    R["zone"] = zone_of
    S.update(cfg=cfg, R=R, zones=zones)
    S["report"]["alpha"] = cfg["alpha"]
    pickle.dump(S, open(RESULTS, "wb"))
    import reports
    reports.write_all(S)
    log(f"пересчитано без обучения: зон {len(zones)}")
    return S


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh()
    else:
        main(fast="--fast" in sys.argv, test="--test" in sys.argv)
