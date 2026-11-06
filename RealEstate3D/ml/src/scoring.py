"""Итоговый балл здания, профили, правила безопасности и объяснения простыми словами.

ВАЖНО: те же формулы и тексты повторены в карте (make_map.py, JS-функции profileScore / explain).
Меняя здесь, меняйте и там. Числа берутся из одной таблицы, поэтому карта и building_report совпадают.
"""
import math

import numpy as np

PROFILE_PARTS = ["exit", "city", "lastmile", "object", "rail_cluster"]
PART_RU = {"exit": "Выезд из города", "city": "Доставка по городу", "lastmile": "Последняя миля (подъезд)",
           "object": "Само здание и место вокруг", "rail_cluster": "Ж/д и соседние склады"}
RULE_BITS = {"no_access": 1, "yard": 2, "residential_type": 4, "residential_quarter": 8, "small": 16}
NONRES_KNOWN = {"industrial", "warehouse", "hangar", "storage", "manufacture", "factory", "commercial", "retail",
                "office", "service", "supermarket", "transportation", "garages", "garage"}


def clip(v, a=0.0, b=100.0):
    return np.minimum(np.maximum(v, a), b)


def f0(v):
    """Округление до целого «по-школьному» (.5 вверх) — так же, как в карте."""
    return str(int(math.floor(v + 0.5)))


def f1(v):
    """Одна цифра после запятой, .05 вверх (как в карте)."""
    x = math.floor(v * 10 + 0.5) / 10
    return f"{x:.1f}".replace(".", ",")


def r10(v):
    """Метры, округлённые до 10."""
    return str(int(math.floor(v / 10 + 0.5) * 10))


# ---------------------------------------------------------------- подбаллы (Python, один раз)
def subscores(X, b, wh_n_1000, cfg):
    s = cfg["subscores"]
    sc = lambda t: clip(100 * (s["exit_worst_min"] - t) / (s["exit_worst_min"] - s["exit_best_min"]))
    exit_ = s["exit_best_share"] * sc(X["t_best"].to_numpy()) + s["exit_backup_share"] * sc(X["t_backup"].to_numpy())
    cm = X["city_mean_min"].to_numpy()
    city = (1 - s["city_share_weight"]) * clip(100 * (s["city_mean_bad_min"] - cm) /
                                               (s["city_mean_bad_min"] - s["city_mean_good_min"])) \
        + s["city_share_weight"] * 100 * X["city_share_25"].to_numpy()
    lm = 100 - s["lastmile_len_penalty"] * clip((X["lm_len_m"].to_numpy() - s["lastmile_len_ok_m"]) /
                                                 (s["lastmile_len_bad_m"] - s["lastmile_len_ok_m"]), 0, 1) \
        - s["lastmile_res_penalty"] * clip(X["lm_res_share"].to_numpy(), 0, 1) \
        - s["lastmile_turns_penalty"] * clip(X["lm_turns"].to_numpy() / s["lastmile_turns_bad"], 0, 1) \
        - s["lastmile_dead_end_penalty"] * X["lm_dead_end"].to_numpy() \
        - s["lastmile_narrow_penalty"] * clip(X["lm_narrow_m"].to_numpy() / 200, 0, 1) \
        - s["lastmile_snap_penalty"] * clip((X["d_truck_road_m"].to_numpy() - s["lastmile_snap_ok_m"]) /
                                            (s["lastmile_snap_bad_m"] - s["lastmile_snap_ok_m"]), 0, 1)
    lm = np.where(X["lm_has_path"].to_numpy() > 0, clip(lm), 0.0)
    area = b["area_m2"].to_numpy(dtype=float)
    area_sc = clip(100 * (area - s["object_area_bad_m2"]) / (s["object_area_good_m2"] - s["object_area_bad_m2"]))
    type_sc = np.where(b["is_res_type"], 0.0, np.where(b["building"].isin(NONRES_KNOWN), 100.0, 50.0))
    obj = 0.5 * area_sc + 0.3 * 100 * X["free_share_30"].to_numpy() + 0.2 * type_sc
    rail = clip(100 * (s["rail_bad_m"] - X["d_rail_m"].to_numpy()) / (s["rail_bad_m"] - s["rail_good_m"]))
    rc = 0.5 * rail + 0.5 * clip(100 * wh_n_1000 / s["cluster_good_n"])
    return {k: np.round(v, 1) for k, v in
            {"exit": exit_, "city": city, "lastmile": lm, "object": obj, "rail_cluster": rc}.items()}


def rule_mask(X, b, side, cfg):
    rules = {r["id"]: r for r in cfg["rules"]}
    m = np.zeros(len(X), dtype=int)
    no_access = (X["lm_has_path"].to_numpy() == 0)
    m |= np.where(no_access, RULE_BITS["no_access"], 0)
    r = rules["yard"]
    yard = (X["lm_res_share"].to_numpy() > r["share"]) | (X["lm_yard_m"].to_numpy() > r["meters"])
    m |= np.where(yard & ~no_access, RULE_BITS["yard"], 0)
    m |= np.where(b["is_res_type"].to_numpy(), RULE_BITS["residential_type"], 0)
    rq = side["yard_landuse"].to_numpy() & (b["building"].to_numpy() == "yes")
    m |= np.where(rq, RULE_BITS["residential_quarter"], 0)
    m |= np.where(b["area_m2"].to_numpy() < rules["small"]["min_area_m2"], RULE_BITS["small"], 0)
    return m


def cap_of(mask, cfg):
    cap = 100.0
    for r in cfg["rules"]:
        if mask & RULE_BITS[r["id"]]:
            cap = min(cap, r["cap"])
    return cap


def profile_score(ml, subs, mask, profile, cfg):
    """Итог здания для профиля (скаляр) — та же арифметика, что в карте."""
    w = cfg["profiles"][profile]["weights"]
    wsum = 0.0
    acc = 0.0
    for k in PROFILE_PARTS:
        acc += w[k] * subs[k]
        wsum += w[k]
    a = cfg["alpha"]
    total = a * ml + (1 - a) * (acc / wsum)
    return min(total, cap_of(int(mask), cfg))


def badge(total, cfg):
    for bd in cfg["badges"]:
        if total >= bd["min"]:
            return bd
    return cfg["badges"][-1]


# ---------------------------------------------------------------- объяснения простыми словами
def plain_reason(r):
    pairs = [("тип дороги track", "полевая дорога"), ("тип дороги living_street", "жилая зона"),
             ("тип дороги construction", "дорога строится"), ("тип дороги proposed", "дорога проектируется"),
             ("грунт", "грунтовая дорога"), ("motor_vehicle=no", "проезд закрыт"), ("access=no", "проезд закрыт"),
             ("vehicle=no", "проезд закрыт"), ("грузовым запрещено (OSM)", "грузовым запрещено")]
    for k, v in pairs:
        if r.startswith(k):
            return v
    return r


def qn(name):
    """Название выезда в кавычках (у «Каспия» кавычки уже есть)."""
    return name if name.startswith("«") else f"«{name}»"


def group_text(g, v, positive):
    """Текст «за» или «против» для группы признаков. Пишем только то, что подтверждают сами факты,
    иначе None (причина не показывается). v — словарь значений здания (как в карте)."""
    if g == "exit":
        if v["best"] is None:
            return None if positive else "нет пути фуры ни к одному выезду"
        t = f"выезд {qn(v['best'])} — {f0(v['t_best'])} мин"
        if v["backup"] is not None:
            t += f", запасной {qn(v['backup'])} — {f0(v['t_backup'])} мин"
        if positive:
            return "рядом " + t if v["t_best"] <= 20 else None
        return "далеко до выездов: " + t if v["t_best"] > 15 else None
    if g == "lastmile":
        if not v["has_path"]:
            return None if positive else "нет пути фуры до магистрали"
        if positive:
            if v["lm_len"] > 800 or v["lm_yard"] >= 200:
                return None
            t = f"до магистрали {r10(v['lm_len'])} м по дорогам для фур"
            return t + ", без жилых дворов" if v["lm_yard"] < 50 else t
        if v["lm_yard"] >= 100:
            return f"подъезд идёт {r10(v['lm_yard'])} м по жилым улицам и дворам"
        if v["lm_len"] > 800:
            return f"до магистрали далеко: {r10(v['lm_len'])} м"
        return None
    if g == "env":
        if positive:
            if v["res_n_200"] > 10:
                return None
            t = f"вокруг мало жилья: в 200 м жилых домов {f0(v['res_n_200'])}"
            return t + ", школ и детсадов рядом нет" if v["d_school"] >= 500 else t
        if v["res_n_200"] >= 10:
            t = f"рядом жильё: в 200 м жилых домов {f0(v['res_n_200'])}"
            return t + f", школа или детсад в {r10(v['d_school'])} м" if v["d_school"] < 300 else t
        if v["d_school"] < 300:
            return f"школа или детсад в {r10(v['d_school'])} м"
        return None
    if g == "city":
        if positive:
            if v["city_share_25"] < 0.35 and v["city_center"] > 20:
                return None
            return f"до центра города {f0(v['city_center'])} мин, {f0(100 * v['city_share_25'])}% городского спроса в 25 мин"
        if v["city_mean"] >= 30:
            return f"далеко от покупателей в городе: в среднем {f0(v['city_mean'])} мин до центров спроса"
        return None
    if g == "infra":
        if positive:
            if v["d_rail"] < 1000:
                return f"ж/д ветка в {r10(v['d_rail'])} м"
            if v["free"] >= 0.8:
                return f"вокруг свободно: {f0(100 * v['free'])}% площади в 30 м не застроено"
            return None
        if v["free"] < 0.6:
            return f"вокруг тесно: свободно только {f0(100 * v['free'])}% площади в 30 м"
        if v["d_rail"] >= 1500:
            return f"ж/д далеко ({f1(v['d_rail'] / 1000)} км)"
        return None
    return None


GROUP_ORDER = ["exit", "lastmile", "env", "city", "infra"]


def explain(v, contrib, cfg):
    """Причины «за» (3), «против» (3) и предупреждения. contrib — вклад групп в балл модели (в пунктах)."""
    pos = sorted([g for g in GROUP_ORDER if contrib[g] >= 1], key=lambda g: (-contrib[g], GROUP_ORDER.index(g)))
    neg = sorted([g for g in GROUP_ORDER if contrib[g] <= -1], key=lambda g: (contrib[g], GROUP_ORDER.index(g)))
    pros = [t for t in (group_text(g, v, True) for g in pos) if t][:3]
    cons = [t for t in (group_text(g, v, False) for g in neg) if t][:3]
    warn = []
    if not v["has_path"]:
        warn.append("нет пути фуры до магистрали по дорогам, открытым для грузовиков")
    elif v["lm_yard"] >= 200:
        warn.append(f"по пути к магистрали {r10(v['lm_yard'])} м жилых улиц и дворов")
    if v["res_n_100"] >= 10 or v["res_share_200"] >= 0.5:
        warn.append("внутри жилой застройки: шум и недовольство жителей")
    if v["d_school"] < 300:
        warn.append(f"школа или детсад в {r10(v['d_school'])} м")
    if v["restr_d"] < 1000:
        warn.append(f"в {r10(v['restr_d'])} м ограничение для фур: {plain_reason(v['restr_reason'])}")
    if v["dead_end"]:
        warn.append("здание на тупиковом проезде: фуре нужно место для разворота")
    if v["oneway"] >= 2:
        warn.append(f"на пути к магистрали односторонних участков: {f0(v['oneway'])}")
    if v["narrow"] >= 50:
        warn.append(f"узкие проезды на пути: {r10(v['narrow'])} м")
    if v["closed_gap"] > 50 and v["closed_reason"]:
        warn.append(f"ближайшая дорога закрыта для фур ({plain_reason(v['closed_reason'])}), объезд {r10(v['closed_gap'])} м")
    if v["d_center"] < 3:
        warn.append("близко к центру: там чаще действуют ограничения для грузовиков")
    if v["no_path_exits"]:
        warn.append("нет пути фуры до: " + ", ".join(v["no_path_exits"]))
    rules = [r["text"] for r in cfg["rules"] if v["mask"] & RULE_BITS[r["id"]]]
    return {"pros": pros or ["заметных преимуществ нет"], "cons": cons, "warnings": warn, "rules": rules}
