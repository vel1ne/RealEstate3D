"""Выходные файлы: warehouse_sites.xlsx, model_report.json, model_report.html, warehouse_results.sqlite."""
import html, json, sqlite3

import numpy as np
import pandas as pd
from openpyxl.styles import Font

import build_model as bm
import features as F
import scoring as sc
import train_model as tm
from paths import OUT


def texts(R, i, cfg, profile):
    r = R.iloc[i]
    v = bm.values_for(r, cfg)
    ex = sc.explain(v, {g: float(r["c_" + g]) for g in F.FEATURE_GROUPS}, cfg)
    return v, ex


def zones_table(S):
    cfg, R, Z = S["cfg"], S["R"], S["zones"]
    p = cfg["default_profile"]
    rows = []
    for zid, z in Z.iterrows():
        v, ex = texts(R, z["best"], cfg, p)
        rows.append({"Зона": zid, "Балл (лучшее здание)": float(sc.f0(z["score"])),
                     "Оценка": sc.badge(z["score"], cfg)["label"], "Улицы": z["streets"],
                     "Площадь, га": round(z["area_ha"]), "Средний балл нежилых зданий": round(z["mean_score"], 1),
                     "Подходящих зданий (≥ 55)": z["n_suitable"], "Отличных зданий (≥ 75)": z["n_good"],
                     "Лучшее здание": R.at[z["best"], "addr_full"],
                     "Топ-3 здания": "; ".join(f"{R.at[j, 'addr_full']} — {sc.f0(R.at[j, 'total_' + p])}" for j in z["top3"]),
                     **{f"{k}, мин": (round(t, 1) if t is not None else None) for k, t in v["times"].items()},
                     "Почему": "; ".join(ex["pros"]), "Что мешает": "; ".join(ex["cons"]) or "—",
                     "Предупреждения": "; ".join(ex["warnings"]) or "нет",
                     "lat": R.at[z["best"], "lat"], "lon": R.at[z["best"], "lon"]})
    return pd.DataFrame(rows)


def buildings_table(S, profile, n=200):
    cfg, R = S["cfg"], S["R"]
    idx = R.sort_values(["total_" + profile, "ml"], ascending=False).index[:n]
    rows = []
    for i in idx:
        r = R.iloc[i]
        v, ex = texts(R, i, cfg, profile)
        rows.append({"Место": len(rows) + 1, "Адрес": r["addr_full"], "Название": r["name"], "Тип": r["type_ru"],
                     "Площадь, м²": int(r["area_m2"]), "Итог": float(r["total_" + profile]),
                     "Оценка": sc.badge(r["total_" + profile], cfg)["label"],
                     "Модель: лучше, чем % зданий": float(r["ml"]),
                     **{sc.PART_RU[k]: float(r["s_" + k]) for k in sc.PROFILE_PARTS},
                     **{f"{k}, мин": (round(t, 1) if t is not None else None) for k, t in v["times"].items()},
                     "До центра, мин": round(v["city_center"], 1), "Последняя миля, м": round(v["lm_len"]),
                     "По жилым улицам и дворам, м": round(v["lm_yard"]),
                     "Почему": "; ".join(ex["pros"]), "Что мешает": "; ".join(ex["cons"]) or "—",
                     "Предупреждения": "; ".join(ex["warnings"]) or "нет",
                     "Правило": "; ".join(ex["rules"]) or "—", "Зона": int(r["zone"]) or None,
                     "osm_id": int(r["osm_id"]), "lat": r["lat"], "lon": r["lon"]})
    return pd.DataFrame(rows)


def quality_table(S):
    s = S["summary"].copy()
    s["Модель"] = s["model"].map(tm.MODEL_RU)
    s["Метка"] = s["variant"].map({"A": "A: склады против всех зданий", "B": "B: склады против жилых домов"})
    pm = lambda m, sd: f"{m:.3f} ± {sd:.3f}"
    out = pd.DataFrame({
        "Метка обучения": s["Метка"], "Модель": s["Модель"],
        "ROC-AUC (среднее ± разброс по районам)": [pm(a, b) for a, b in zip(s["roc_auc"], s["roc_auc_std"])],
        "Average Precision": [pm(a, b) for a, b in zip(s["ap"], s["ap_std"])],
        f"Precision@{S['cfg']['model']['precision_at']}": [pm(a, b) for a, b in zip(s["p_at_k"], s["p_at_k_std"])],
        "ROC-AUC: склады против жилых": s["roc_auc_B"].round(3), "AP: склады против жилых": s["ap_B"].round(3)})
    return out


def write_all(S):
    cfg, R = S["cfg"], S["R"]
    zt = zones_table(S)
    S["zones_table"] = zt
    btabs = {p: buildings_table(S, p) for p in cfg["profiles"]}
    q = quality_table(S)
    abl = S["ablation"].copy()
    abl["Что убрали"] = abl["group"].map(lambda g: "ничего (все признаки)" if g == "все признаки" else F.GROUP_RU[g])
    abl = abl[["Что убрали", "roc_auc", "ap", "auc_loss", "ap_loss"]].rename(columns={
        "roc_auc": "ROC-AUC", "ap": "Average Precision", "auc_loss": "Потеря ROC-AUC", "ap_loss": "Потеря AP"}).round(4)
    imp = S["importance"].rename("Падение AP, если перемешать признак").to_frame()
    imp.insert(0, "Группа", [next(F.GROUP_RU[g] for g, fs in F.FEATURE_GROUPS.items() if f in fs) for f in imp.index])
    imp.insert(0, "Признак", [F.FEATURE_RU.get(f, f) for f in imp.index])
    imp = imp.reset_index(drop=True).round(5)
    err = S["errors"].rename(columns={"addr_full": "адрес", "type_ru": "тип", "area_m2": "площадь, м²",
                                      "street_near": "улица", "p_model": "прогноз модели", "ml": "лучше, чем %",
                                      "label_why": "почему склад по OSM", "t_best": "до выезда, мин",
                                      "lm_yard_m": "по дворам, м", "res_n_200": "жилых в 200 м", "d_rail_m": "до ж/д, м"})
    feats = R[["osm_id", "addr_full", "type_ru", "area_m2", "label_A"] + F.FEATURES].head(5000).rename(
        columns={**F.FEATURE_RU, "addr_full": "адрес", "type_ru": "тип", "area_m2": "площадь, м²",
                 "label_A": "метка A (склад сейчас)"})
    exits = pd.DataFrame([{"Выезд": k, "Точка": "вся СКАД" if v["lonlat"] is None else
                           f"{v['lonlat'][1]:.5f}, {v['lonlat'][0]:.5f}",
                           "Доля фур (допущение)": cfg["exits"]["share"][k], "До СКАД, м": round(v["gap_m"])}
                          for k, v in S["exits"].items()])
    calib = S["calibration"].rename(columns={"range": "прогноз (калибр.)", "n": "зданий",
                                             "predicted": "средний прогноз", "observed": "доля складов на деле"}).round(3)
    path = OUT / "warehouse_sites.xlsx"
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        zt.to_excel(xw, sheet_name="Лучшие зоны", index=False)
        for p, t in btabs.items():
            name = "Лучшие здания — " + cfg["profiles"][p]["name"]
            t.to_excel(xw, sheet_name=name if len(name) <= 31 else ("Здания — " + cfg["profiles"][p]["name"])[:31],
                       index=False)
        q.to_excel(xw, sheet_name="Качество модели", index=False)
        start = len(q) + 3
        abl.to_excel(xw, sheet_name="Качество модели", index=False, startrow=start)
        calib.to_excel(xw, sheet_name="Качество модели", index=False, startrow=start + len(abl) + 3)
        imp.to_excel(xw, sheet_name="Важность признаков", index=False)
        err.to_excel(xw, sheet_name="Ошибки модели", index=False)
        feats.to_excel(xw, sheet_name="Признаки зданий", index=False)
        exits.to_excel(xw, sheet_name="Выезды", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                width = max(len(str(c.value)) if c.value is not None else 0 for c in list(col)[:60])
                ws.column_dimensions[col[0].column_letter].width = min(max(10, width + 2), 60)
            for c in ws[1]:
                c.font = Font(bold=True)
        qs = xw.book["Качество модели"]
        qs.cell(row=start, column=1, value="Исследование по группам признаков: качество без каждой группы")
        qs.cell(row=start + len(abl) + 3, column=1, value="Калибровка итоговой модели (проверочные районы)")
    tm.log(f"  Excel: {path}")

    rep = dict(S["report"])
    rep["Модели (среднее по районам)"] = S["summary"].round(4).to_dict(orient="records")
    rep["Исследование групп признаков"] = abl.to_dict(orient="records")
    rep["Важность признаков (топ-15)"] = imp.head(15).to_dict(orient="records")
    rep["Калибровка"] = calib.to_dict(orient="records")
    rep["Лучшие зоны"] = zt.head(15)[["Зона", "Балл (лучшее здание)", "Улицы", "Лучшее здание", "Почему"]].to_dict(orient="records")
    json.dump(rep, open(OUT / "model_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
    write_html(S, q, abl, imp, err, zt, calib)
    write_sqlite(S, zt)


def _t(df, n=None):
    df = df if n is None else df.head(n)
    return df.to_html(index=False, border=0, classes="t", na_rep="—", escape=True)


def write_html(S, q, abl, imp, err, zt, calib):
    rep, cfg = S["report"], S["cfg"]
    s = S["summary"].set_index(["variant", "model"])
    final = rep["Итоговая модель"]
    f_ap, m_ap = s.loc[("A", "formula"), "ap"], s.loc[("A", final), "ap"]
    f_auc, m_auc = s.loc[("A", "formula"), "roc_auc"], s.loc[("A", final), "roc_auc"]
    base = rep["Доля положительных"]
    best_b = s.loc["B"]["ap_B"].idxmax()
    doc = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Модель складов: отчёт</title><style>
:root{{--bg:#fbfaf7;--ink:#1f2429;--muted:#5f6771;--line:#dedbd2;--accent:#1a7f37}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 "Segoe UI",system-ui,sans-serif}}
main{{max-width:980px;margin:0 auto;padding:24px 16px 48px}} h1{{font-size:24px;margin:0 0 4px}} h2{{font-size:18px;margin:28px 0 8px}}
.lead{{color:var(--muted)}} .kpi{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px;margin:16px 0}}
.kpi div{{background:#fff;border:1px solid var(--line);border-radius:8px;padding:10px 12px}} .kpi b{{display:block;font-size:22px}}
table.t{{border-collapse:collapse;width:100%;font-size:13px;background:#fff}} .t th,.t td{{border-bottom:1px solid var(--line);padding:5px 6px;text-align:left;vertical-align:top}}
.t th{{font-size:12px;color:var(--muted)}} .scroll{{overflow-x:auto}} .note{{background:#fff7e6;border:1px solid #f0d9a8;border-radius:8px;padding:10px 14px}}
</style></head><body><main>
<h1>Где ставить склад в Саратове — отчёт по модели</h1>
<p class="lead">Расчёт {html.escape(rep["Дата расчёта"])}. Оценено зданий: {rep["Зданий оценено"]:,}. Дороги — база дата-инженера ({html.escape(rep["База дорог"])}), здания и объекты — OpenStreetMap.</p>
<div class="kpi">
<div>Итоговая модель<b>{html.escape(tm.MODEL_RU[final])}</b></div>
<div>ROC-AUC на незнакомых районах<b>{m_auc:.3f}</b>у формулы {f_auc:.3f}</div>
<div>Average Precision<b>{m_ap:.3f}</b>у формулы {f_ap:.3f}, у случайного угадывания {base:.3f}</div>
<div>Во сколько раз лучше формулы (AP)<b>{m_ap / f_ap:.1f}×</b></div>
</div>
<h2>Что модель учит и чего она не знает</h2>
<p>Модель видит {rep["Складов/производств (метка A)"]:,} зданий, которые сейчас по OSM являются складами, производствами или нежилыми зданиями в промзонах, и учится отличать их место от мест остальных зданий: по времени фуры до выездов, по последней миле до магистрали, по жилью вокруг, по доступности города и ж/д.
Поэтому её балл означает <b>«место похоже на те, где склады уже стоят»</b>, а не «здесь лучше всего». Часть складов — старая промышленность внутри города, и модель считает похожие места хорошими.
Чтобы назвать место лучшим, нужна оценка людей, знающих рынок (страница разметки <code>label.html</code>), и данные, которых у нас нет: цены, аренда, свободные участки, мощности, санитарные зоны, объявления.</p>
<div class="note">Экспертная разметка: {html.escape(json.dumps(rep["Экспертная разметка"], ensure_ascii=False) if isinstance(rep["Экспертная разметка"], dict) else str(rep["Экспертная разметка"]))}</div>
<h2>Сравнение моделей на одних и тех же районах</h2>
<p>Проверка: {html.escape(rep["Проверка"])}. Подбор гиперпараметров: {html.escape(rep["Подбор гиперпараметров"])}. «±» — разброс между районами.
Precision@{cfg["model"]["precision_at"]} — доля настоящих складов среди 100 зданий, которые модель поставила выше всех в незнакомом районе.</p>
<div class="scroll">{_t(q)}</div>
<h2>Вариант A против варианта B</h2>
<p><b>A</b> учится отличать склады от всех остальных зданий (среди «остальных» есть и неотмеченные склады — это шум в метке).
<b>B</b> учится только на надёжных примерах: склады против жилых домов; здания без типа в обучение не идут.
B лучше всего разделяет «склад или жильё» (AP {s.loc[("B", best_b), "ap_B"]:.3f}), но хуже ранжирует все здания города, потому что не видел гаражей, магазинов и зданий без типа.
Для итогового балла взят вариант {cfg["labels"]["main_variant"]}.</p>
<h2>Что даёт каждая группа признаков</h2><p>Модель обучали заново без одной группы. Чем больше потеря, тем важнее группа.</p>
<div class="scroll">{_t(abl)}</div>
<h2>Важные признаки</h2><div class="scroll">{_t(imp, 15)}</div>
<h2>Калибровка</h2><p>Brier до калибровки {rep["Brier до калибровки"]}, после {rep["Brier после калибровки"]}. Ниже: если модель говорит «вероятность 0.3», доля складов среди таких зданий на деле.</p>
<div class="scroll">{_t(calib)}</div>
<h2>Монотонность</h2><p>{html.escape(json.dumps(rep["Монотонность (СКАД −5 мин)"], ensure_ascii=False))}</p>
<h2>Лучшие зоны</h2><div class="scroll">{_t(zt[["Зона", "Балл (лучшее здание)", "Улицы", "Площадь, га", "Отличных зданий (≥ 75)", "Лучшее здание", "Почему", "Предупреждения"]], 15)}</div>
<h2>Ошибки модели</h2><p>20 зданий, которые модель считает самыми «складскими», хотя склада по OSM нет, и 20 складов, которые она не узнала.</p>
<div class="scroll">{_t(err[["ошибка", "адрес", "тип", "площадь, м²", "лучше, чем %", "что это за место"]])}</div>
<h2>Допущения и чего мы не знаем</h2><ul>
<li>Пробки статические: модель загруженности из Colab, а не данные по часам.</li>
<li>Потоки фур модельные; доли фур по выездам (по 25%) — допущение.</li>
<li>Метка модели — существующие склады OSM, а не экспертная оценка «хорошо/плохо».</li>
<li>Спрос по городу — кластеры жилья и магазинов OSM (населения нет).</li>
<li>Нет цен, аренды, свободных участков, мощностей, санитарных зон и объявлений.</li>
<li>Ограничения для фур — из OSM и нашего ручного списка мостов; список неполный.</li></ul>
<p class="lead">Итог здания = {cfg["alpha"]}·балл модели + {1 - cfg["alpha"]:.1f}·формула профиля, затем правила безопасности (≤ 20 без проезда, ≤ 40 через жилые дворы, ≤ 30 жилой дом, ≤ 50 меньше 100 м²).</p>
</main></body></html>"""
    (OUT / "model_report.html").write_text(doc, encoding="utf-8")


def write_sqlite(S, zt):
    cfg, R = S["cfg"], S["R"]
    path = OUT / "warehouse_results.sqlite"
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    cols = ["osm_id", "lat", "lon", "addr_full", "name", "type_ru", "area_m2", "ml", "p_calibrated"] + \
        ["s_" + k for k in sc.PROFILE_PARTS] + ["total_" + p for p in cfg["profiles"]] + ["mask", "zone"] + \
        ["t_" + F.EXIT_KEY[k] for k in cfg["exits"]["names"]] + ["city_center_min", "city_mean_min", "lm_len_m",
                                                                  "lm_yard_m", "res_n_200", "d_rail_m", "label_A"]
    R[cols].rename(columns={"addr_full": "address", "type_ru": "building_type", "ml": "model_pct",
                            "mask": "rules_mask", "zone": "zone_id"}).to_sql("wh_building_score", con, index=False)
    zt.drop(columns=[]).to_sql("wh_zone", con, index=False)
    S["summary"].to_sql("wh_model_metric", con, index=False)
    S["importance"].rename("importance").rename_axis("feature").reset_index().to_sql("wh_feature_importance", con, index=False)
    pd.DataFrame([{"created_at": S["report"]["Дата расчёта"], "road_dataset_key": S["report"]["База дорог"],
                   "config_json": json.dumps(cfg, ensure_ascii=False),
                   "report_json": json.dumps(S["report"], ensure_ascii=False, default=str)}]).to_sql("wh_run", con, index=False)
    con.execute("create index ix_b_osm on wh_building_score(osm_id)")
    con.commit()
    con.close()
    tm.log(f"  SQLite: {path}")
