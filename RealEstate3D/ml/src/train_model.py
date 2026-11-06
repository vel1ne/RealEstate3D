"""Обучение и честная проверка модели «насколько место подходит под склад».

Метка (что модель учит): где склады и производства стоят СЕЙЧАС (OSM). Это не «где лучше всего».
  Вариант A: положительные — здания с тегом склада/производства и нежилые здания внутри промзон;
             все остальные здания — отрицательные (с весами классов).
  Вариант B: положительные те же; отрицательные — только жилые дома (тип в OSM);
             остальные здания в обучение не идут, но получают оценку.
Модели (на одних и тех же разбиениях): формула с ручными весами, логистическая регрессия,
градиентный бустинг, бустинг с монотонными ограничениями.
Проверка: GroupKFold по блокам 3×3 км — модель оценивается на районах, которых не видела.
Гиперпараметры подбираются только внутри обучающих блоков (вложенная проверка).
"""
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from features import FEATURE_GROUPS, FEATURES, MONOTONIC

MODEL_RU = {"formula": "Формула с ручными весами (старые подбаллы)", "logreg": "Логистическая регрессия",
            "hgb": "Градиентный бустинг", "hgb_mono": "Градиентный бустинг с монотонными ограничениями"}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- метки
def make_labels(b, side, cfg):
    c = cfg["labels"]
    btype = b["building"]
    tagged = btype.isin(c["positive_types"]).to_numpy()
    in_zone = side["in_industrial"].to_numpy() & ~b["is_res_type"].to_numpy() \
        & ~btype.isin(c["zone_exclude_types"]).to_numpy() & (b["area_m2"].to_numpy() >= c["zone_min_area_m2"]) \
        & ~side["yard_landuse"].to_numpy()
    pos = tagged | in_zone
    y_a = pos.astype(int)
    y_b = np.where(pos, 1.0, np.where(b["is_res_type"].to_numpy(), 0.0, np.nan))
    why = np.where(tagged, "тег склада/производства", np.where(in_zone, "нежилое здание в промзоне", ""))
    return {"A": y_a, "B": y_b, "why": why, "positive": pos}


def spatial_blocks(b, km):
    s = km * 1000
    return ((b["x"] // s).astype(int).astype(str) + "_" + (b["y"] // s).astype(int).astype(str)).to_numpy()


# ---------------------------------------------------------------- формула (базовая линия)
def formula_score(X, cfg):
    """Старые подбаллы без ML: выезд 40, подъезд 25, соседство 15 (нормировано)."""
    s = cfg["subscores"]
    sc = lambda t: np.clip(100 * (s["exit_worst_min"] - t) / (s["exit_worst_min"] - s["exit_best_min"]), 0, 100)
    ex = s["exit_best_share"] * sc(X["t_best"]) + s["exit_backup_share"] * sc(X["t_backup"])
    road = 60 * np.clip((X["d_truck_road_m"] - 50) / 450, 0, 1)
    res = 25 * np.clip(X["lm_yard_m"] / 1000, 0, 1)
    restr = 15 * np.clip(1 - X["restr_dist_m"] / 1000, 0, 1)
    ac = np.clip(100 - road - res - restr, 0, 100)
    nb = 0.7 * 100 * (1 - X["res_share_200"]) + 0.3 * 100 * np.clip(X["d_center_km"] / 8, 0, 1)
    return ((0.40 * ex + 0.25 * ac + 0.15 * nb) / 0.80).to_numpy() / 100


# ---------------------------------------------------------------- модели
def make_model(kind, params, cfg, features):
    rs = cfg["random_state"]
    if kind == "logreg":
        return make_pipeline(StandardScaler(), LogisticRegression(C=params["C"], class_weight="balanced",
                                                                   max_iter=3000, random_state=rs))
    p = {k: v for k, v in params.items()}
    mono = [MONOTONIC.get(f, 0) for f in features] if kind == "hgb_mono" else None
    return HistGradientBoostingClassifier(class_weight="balanced", random_state=rs, early_stopping=False,
                                          monotonic_cst=mono, **p)


def param_grid(kind, cfg):
    if kind == "logreg":
        return [{"C": c} for c in cfg["model"]["logreg_C"]]
    return cfg["model"]["hgb_grid"]


def precision_at(y, p, k):
    k = min(k, len(y))
    return float(np.mean(y[np.argsort(-p)[:k]])) if k else np.nan


def fit_tuned(kind, X, y, groups, cfg, features, fast=False):
    """Подбор гиперпараметров только по обучающим блокам (внутренняя GroupKFold)."""
    grid = param_grid(kind, cfg)
    if fast or len(grid) == 1:
        best = grid[0]
    else:
        inner = GroupKFold(n_splits=cfg["model"]["inner_folds"])
        scores = []
        for prm in grid:
            ap = []
            for tr, va in inner.split(X, y, groups):
                if y[va].sum() == 0:
                    continue
                m = make_model(kind, prm, cfg, features).fit(X[tr], y[tr])
                ap.append(average_precision_score(y[va], m.predict_proba(X[va])[:, 1]))
            scores.append(np.mean(ap))
        best = grid[int(np.argmax(scores))]
    return make_model(kind, best, cfg, features).fit(X, y), best


def evaluate_models(X, labels, groups, cfg, variant, kinds=("formula", "logreg", "hgb", "hgb_mono"),
                    features=FEATURES, fast=False):
    """Внешняя проверка по блокам. Возвращает метрики по фолдам, OOF-прогнозы и модели фолдов.
    Обучение — на метке варианта (A или B); оценка — и на метке A (все здания), и на метке B
    (склады против жилых домов), чтобы A и B сравнивались на одних и тех же зданиях."""
    yA = labels["A"]
    yB = labels["B"]
    y_train = yA if variant == "A" else yB
    Xn = X[features].to_numpy(dtype=float)
    folds = list(GroupKFold(n_splits=cfg["model"]["folds"]).split(Xn, yA, groups))
    rows, oof, models, chosen = [], {k: np.zeros(len(X)) for k in kinds}, {k: [] for k in kinds}, {k: [] for k in kinds}
    K = cfg["model"]["precision_at"]
    for fi, (tr, te) in enumerate(folds):
        trm = tr[~np.isnan(y_train[tr])] if variant == "B" else tr
        for kind in kinds:
            t0 = time.time()
            if kind == "formula":
                p = formula_score(X.iloc[te], cfg)
                m, prm = None, {}
            else:
                m, prm = fit_tuned(kind, Xn[trm], y_train[trm].astype(int), groups[trm], cfg, features, fast)
                p = m.predict_proba(Xn[te])[:, 1]
            oof[kind][te] = p
            models[kind].append(m)
            chosen[kind].append(prm)
            ya = yA[te]
            yb = yB[te]
            mb = ~np.isnan(yb)
            rows.append({"variant": variant, "model": kind, "fold": fi, "n_test": len(te), "pos_test": int(ya.sum()),
                         "roc_auc": roc_auc_score(ya, p) if 0 < ya.sum() < len(ya) else np.nan,
                         "ap": average_precision_score(ya, p) if ya.sum() else np.nan,
                         "p_at_k": precision_at(ya, p, K),
                         "roc_auc_B": roc_auc_score(yb[mb], p[mb]) if 0 < np.nansum(yb[mb]) < mb.sum() else np.nan,
                         "ap_B": average_precision_score(yb[mb], p[mb]) if np.nansum(yb[mb]) else np.nan,
                         "seconds": round(time.time() - t0, 1)})
        log(f"  {variant}: фолд {fi + 1}/{len(folds)} готов")
    return pd.DataFrame(rows), oof, models, chosen, folds


def summarize(metrics):
    agg = metrics.groupby(["variant", "model"]).agg(
        roc_auc=("roc_auc", "mean"), roc_auc_std=("roc_auc", "std"), ap=("ap", "mean"), ap_std=("ap", "std"),
        p_at_k=("p_at_k", "mean"), p_at_k_std=("p_at_k", "std"),
        roc_auc_B=("roc_auc_B", "mean"), ap_B=("ap_B", "mean")).reset_index()
    return agg


def cross_calibrate(oof, y, folds):
    """Калибровка вероятностей изотонической регрессией, обученной на ДРУГИХ фолдах."""
    cal = np.zeros(len(oof))
    for tr, te in folds:
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1).fit(oof[tr], y[tr])
        cal[te] = iso.predict(oof[te])
    return cal


def calibration_table(p, y, bins=10):
    q = np.clip((p * bins).astype(int), 0, bins - 1)
    t = pd.DataFrame({"bin": q, "p": p, "y": y}).groupby("bin").agg(
        n=("y", "size"), predicted=("p", "mean"), observed=("y", "mean")).reset_index()
    t["range"] = t["bin"].map(lambda i: f"{i / bins:.1f}–{(i + 1) / bins:.1f}")
    return t[["range", "n", "predicted", "observed"]]


def ablation(X, labels, groups, cfg, kind, params, folds):
    """Качество без каждой группы признаков (та же модель, те же разбиения)."""
    y = labels["A"]
    rows = []
    for g, feats in [("все признаки", [])] + list(FEATURE_GROUPS.items()):
        keep = [f for f in FEATURES if f not in feats]
        Xn = X[keep].to_numpy(dtype=float)
        aps, aucs = [], []
        for tr, te in folds:
            m = make_model(kind, params, cfg, keep).fit(Xn[tr], y[tr])
            p = m.predict_proba(Xn[te])[:, 1]
            aps.append(average_precision_score(y[te], p))
            aucs.append(roc_auc_score(y[te], p))
        rows.append({"group": g, "roc_auc": np.mean(aucs), "ap": np.mean(aps)})
        log(f"  без группы «{g}»: AP {np.mean(aps):.3f}")
    t = pd.DataFrame(rows)
    t["ap_loss"] = t.loc[0, "ap"] - t["ap"]
    t["auc_loss"] = t.loc[0, "roc_auc"] - t["roc_auc"]
    return t


def permutation_groups(models, folds, X, y, features, rs, repeats=2):
    """Важность: насколько падает AP на проверочных районах, если перемешать признак."""
    rng = np.random.default_rng(rs)
    Xn = X[features].to_numpy(dtype=float)
    imp = np.zeros(len(features))
    for m, (tr, te) in zip(models, folds):
        base = average_precision_score(y[te], m.predict_proba(Xn[te])[:, 1])
        for j in range(len(features)):
            drops = []
            for _ in range(repeats):
                Xp = Xn[te].copy()
                Xp[:, j] = rng.permutation(Xp[:, j])
                drops.append(base - average_precision_score(y[te], m.predict_proba(Xp)[:, 1]))
            imp[j] += np.mean(drops) / len(folds)
    return pd.Series(imp, index=features).sort_values(ascending=False)


def group_contributions(models, folds, X, oof, features, pct_fn):
    """Вклад групп признаков в балл модели здания: заменяем группу на медиану по городу
    и смотрим, насколько изменился балл (перцентиль). Положительный вклад — группа «за»."""
    med = X[features].median()
    Xn = X[features].to_numpy(dtype=float)
    base = pct_fn(oof)
    out = {}
    for g, feats in FEATURE_GROUPS.items():
        cols = [features.index(f) for f in feats]
        alt = np.zeros(len(X))
        for m, (tr, te) in zip(models, folds):
            Xp = Xn[te].copy()
            Xp[:, cols] = med[feats].to_numpy()
            alt[te] = m.predict_proba(Xp)[:, 1]
        out[g] = base - pct_fn(alt)
    return pd.DataFrame(out)
