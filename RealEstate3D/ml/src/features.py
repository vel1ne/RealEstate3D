"""Признаки зданий: всё, что описывает МЕСТО и подъезд к нему (а не само здание).

Группы признаков (их же выключаем по очереди в «исследовании по группам»):
  exit      — выезд из города: время до СКАД и каждого выезда (туда и обратно), лучший и запасной;
  lastmile  — последняя миля: реальный путь фуры по графу от здания до ближайшей магистрали;
  env       — окружение: жилые дома рядом, школы/детсады/больницы, плотность дорог, центр города;
  city      — достижимость города: время до ~200 центров спроса (кластеры жилья и магазинов OSM);
  infra     — ж/д ветка и станция, свободное место вокруг здания.
Тип здания, landuse, тег склада и площадь здания в признаки НЕ входят: из них строится метка.
"""
import math

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, Point, Polygon
from sklearn.cluster import KMeans
from sklearn.neighbors import KDTree

from osm_data import decode_poly, to_xy, KX, KY
from truck_network import ARTERIAL

CENTER = (46.0342, 51.5331)   # Театральная площадь
REF_NAMES = {"63К-00758": "Вольский тракт", "Р-158": "Московское шоссе", "Р-22": "«Каспий» (Р-22)",
             "Р-228": "СКАД", "А-298": "СКАД", "63К-00777": "Сокурский тракт"}
EXIT_MATCH = {
    "Московское шоссе": lambda w: "Р-158" in (w["ref"] or "") or w["name"] == "Московское шоссе",
    "Вольский тракт": lambda w: w["ref"] == "63К-00758" or w["name"] in ("Вольский тракт", "Балаковский тракт"),
    "Ново-Астраханское шоссе": lambda w: "Ново-Астраханское" in (w["name"] or ""),
    "Сокурский тракт": lambda w: "Сокурский тракт" == w["name"],
    "«Каспий» (Р-22)": lambda w: w["name"] == "«Каспий»" or w["ref"] == "Р-22",
}
EXIT_KEY = {"СКАД": "skad", "Московское шоссе": "moskovskoe", "Вольский тракт": "volsky",
            "Ново-Астраханское шоссе": "novoastr", "Сокурский тракт": "sokursky", "«Каспий» (Р-22)": "kaspiy"}

FEATURE_GROUPS = {
    "exit": ["t_skad", "t_moskovskoe", "t_volsky", "t_novoastr", "t_sokursky", "t_kaspiy",
             "t_best", "t_backup", "n_exits_20"],
    "lastmile": ["lm_has_path", "lm_len_m", "lm_time_min", "lm_res_share", "lm_yard_m", "lm_turns",
                 "lm_dead_end", "lm_oneway_n", "lm_narrow_m", "d_truck_road_m", "d_closed_road_gap_m",
                 "restr_dist_m", "restr_n_1km"],
    "env": ["res_n_100", "res_n_200", "res_n_500", "res_share_100", "res_share_200", "res_share_500",
            "d_school_m", "d_hospital_m", "road_km_500", "d_center_km"],
    "city": ["city_mean_min", "city_center_min", "city_share_15", "city_share_25"],
    "infra": ["d_rail_m", "d_rail_station_m", "free_share_30"],
}
GROUP_RU = {"exit": "выезд из города", "lastmile": "последняя миля", "env": "окружение",
            "city": "достижимость города", "infra": "ж/д и свободное место"}
FEATURES = [f for g in FEATURE_GROUPS.values() for f in g]
# монотонность: +1 — больше значение → балл не падает, −1 — не растёт, 0 — без ограничения
MONOTONIC = {**{f: -1 for f in FEATURE_GROUPS["exit"]}, "n_exits_20": 1,
             "lm_has_path": 1, "lm_len_m": -1, "lm_time_min": -1, "lm_res_share": -1, "lm_yard_m": -1,
             "lm_turns": -1, "lm_dead_end": -1, "lm_oneway_n": -1, "lm_narrow_m": -1, "d_truck_road_m": -1,
             "d_closed_road_gap_m": 1, "restr_dist_m": 1, "restr_n_1km": -1,
             "res_n_100": -1, "res_n_200": -1, "res_n_500": -1, "res_share_100": -1, "res_share_200": -1,
             "res_share_500": -1, "d_school_m": 1, "d_hospital_m": 1, "free_share_30": 1}
FEATURE_RU = {
    "t_skad": "время до СКАД, мин", "t_moskovskoe": "до Московского шоссе, мин", "t_volsky": "до Вольского тракта, мин",
    "t_novoastr": "до Ново-Астраханского шоссе, мин", "t_sokursky": "до Сокурского тракта, мин",
    "t_kaspiy": "до «Каспия», мин", "t_best": "до лучшего выезда, мин", "t_backup": "до запасного выезда, мин",
    "n_exits_20": "выездов в пределах 20 мин", "lm_has_path": "есть путь фуры до магистрали",
    "lm_len_m": "последняя миля, м", "lm_time_min": "последняя миля, мин", "lm_res_share": "доля пути по жилым улицам и дворам",
    "lm_yard_m": "путь по дворам и жилым улицам, м", "lm_turns": "поворотов до магистрали",
    "lm_dead_end": "здание в тупике", "lm_oneway_n": "односторонних участков на пути",
    "lm_narrow_m": "узких проездов на пути, м", "d_truck_road_m": "до дороги, открытой для фур, м",
    "d_closed_road_gap_m": "насколько ближе закрытая для фур дорога, м",
    "restr_dist_m": "до ограничения (мост, высота, масса), м", "restr_n_1km": "ограничений в 1 км",
    "res_n_100": "жилых домов в 100 м", "res_n_200": "жилых домов в 200 м", "res_n_500": "жилых домов в 500 м",
    "res_share_100": "доля жилых в 100 м", "res_share_200": "доля жилых в 200 м", "res_share_500": "доля жилых в 500 м",
    "d_school_m": "до школы/детсада, м", "d_hospital_m": "до больницы, м", "road_km_500": "дорог в 500 м, км",
    "d_center_km": "до центра города, км", "city_mean_min": "среднее время до центров спроса, мин",
    "city_center_min": "до центра города, мин", "city_share_15": "доля спроса в 15 мин",
    "city_share_25": "доля спроса в 25 мин", "d_rail_m": "до ж/д ветки, м", "d_rail_station_m": "до ж/д станции, м",
    "free_share_30": "свободно вокруг здания (30 м)",
}
NO_PATH_MIN = 90.0      # «нет пути» → столько минут (для модели), в карточке пишем «нет пути»


def log(*a):
    import time
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- выезды
def find_exits(net, names):
    skad = {n for w in net.ways if not w["blocked"] and w["name"] == "СКАД" for n in w["nodes"]}
    skad = {n for n in skad if n in net.out_edges or n in net.in_edges}
    sk_tree = KDTree(np.array([to_xy(*net.node_xy[n]) for n in skad]))
    exits = {}
    for name in names:
        if name == "СКАД":
            exits[name] = {"nodes": skad, "lonlat": None, "gap_m": 0}
            continue
        cand = {n: c for w in net.ways if not w["blocked"] and EXIT_MATCH[name](w)
                for n, c in zip(w["nodes"], w["coords"]) if n in net.out_edges or n in net.in_edges}
        ids = list(cand)
        d, _ = sk_tree.query(np.array([to_xy(*cand[n]) for n in ids]), k=1)
        i = int(np.argmin(d[:, 0]))
        exits[name] = {"nodes": {ids[i]}, "lonlat": cand[ids[i]], "gap_m": float(d[i, 0])}
    return exits


# ---------------------------------------------------------------- здания города
def city_buildings(b, industrial, cfg):
    """Только сплошная городская застройка Саратова (посёлки и дачи у СКАД не оцениваем)."""
    c = cfg["buildings"]
    keep = (b["addr"] != "") | (b["name"] != "") | (b["area_m2"] >= c["min_area_m2"])
    b = b[keep].reset_index(drop=True)
    cell = c["city_cell_m"]
    xy = b[["x", "y"]].to_numpy()
    gx, gy = np.floor(xy[:, 0] / cell).astype(int), np.floor(xy[:, 1] / cell).astype(int)
    cells = sorted(set(zip(gx, gy)))
    cxy = np.array([((i + 0.5) * cell, (j + 0.5) * cell) for i, j in cells])
    n300 = KDTree(xy).query_radius(cxy, r=300, count_only=True)
    ind_tree = shapely.STRtree([p["geom"] for p in industrial]) if industrial else None
    in_ind = np.zeros(len(cells), bool)
    if ind_tree is not None:
        hit = ind_tree.query(shapely.points(cxy), predicate="intersects")
        in_ind[np.unique(hit[0])] = True
    dense = {cells[i] for i in range(len(cells)) if n300[i] >= c["city_min_buildings_300m"] or in_ind[i]}
    comp, keep_cells = set(), set()
    for start in dense:
        if start in comp:
            continue
        stack, members = [start], [start]
        comp.add(start)
        while stack:
            i, j = stack.pop()
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    n = (i + di, j + dj)
                    if n in dense and n not in comp:
                        comp.add(n)
                        stack.append(n)
                        members.append(n)
        if len(members) >= c["city_min_cluster_cells"]:
            keep_cells.update(members)
    mask = np.array([(i, j) in keep_cells for i, j in zip(gx, gy)])
    return b[mask].reset_index(drop=True)


def building_polygons(b):
    polys = []
    for flat in b["poly"]:
        pts = [to_xy(lo, la) for lo, la in decode_poly(flat)]
        g = Polygon(pts) if len(pts) >= 4 else Point(pts[0]).buffer(3)
        polys.append(g if g.is_valid else g.buffer(0))
    return np.array(polys, dtype=object)


# ---------------------------------------------------------------- последняя миля (по рёбрам)
def edge_lastmile(net, yard_piece, narrow_piece):
    """Для каждого ребра — путь фуры до ближайшей магистрали (по времени): длина, время, по жилым/дворам,
    повороты, односторонние, узкие. Рёбра самих магистралей — ноль."""
    E = net.E
    art_piece = np.isin(net.p_hw, list(ARTERIAL))
    art_nodes = {net.e_to[e] for e in range(E) if art_piece[net.e_piece[e]]} | \
                {net.e_from[e] for e in range(E) if art_piece[net.e_piece[e]]}
    dist, nxt = net.tree_to(art_nodes)
    pe = net.e_piece_arr
    plen = net.p_len[pe]
    res_hw = np.isin(net.p_hw, ["residential", "living_street"])[pe]
    yard = yard_piece[pe]
    narrow = narrow_piece[pe]
    oneway = np.array(net.e_oneway)
    cum = {k: np.zeros(E) for k in ("len", "res", "yard", "turns", "oneway", "narrow", "time")}
    order = np.argsort(dist)
    is_art = art_piece[pe]
    for e in order:
        if not np.isfinite(dist[e]) or is_art[e]:
            continue
        n = nxt[e]
        own_len = plen[e]
        cum["len"][e] = own_len
        cum["time"][e] = net.et[e]
        cum["res"][e] = own_len if res_hw[e] else 0
        cum["yard"][e] = own_len if yard[e] else 0
        cum["oneway"][e] = 1 if oneway[e] else 0
        cum["narrow"][e] = own_len if narrow[e] else 0
        if n >= 0 and not is_art[n]:
            for k in ("len", "res", "yard", "oneway", "narrow", "time"):
                cum[k][e] += cum[k][n]
            cum["turns"][e] = cum["turns"][n]
            cum["time"][e] += net.turn_cost(e, n)
        if n >= 0 and net.turn_cost(e, n) > 0:
            cum["turns"][e] += 1
    cum["ok"] = np.isfinite(dist)
    return cum


# ---------------------------------------------------------------- основной расчёт
def build_features(net, b, osm, cfg):
    """b — здания города; osm — словарь industrial, res_landuse, rail, poi. Возвращает (таблица, служебное)."""
    log(f"признаки для {len(b)} зданий…")
    exits = find_exits(net, cfg["exits"]["names"])
    trees = {k: {"to": net.tree_to(v["nodes"]), "from": net.tree_from(v["nodes"])} for k, v in exits.items()}
    polys = building_polygons(b)
    bxy = b[["x", "y"]].to_numpy()

    # --- привязка к дорогам: ближайший участок, открытый для фур, и ближайшая дорога вообще
    piece_lines = [LineString([to_xy(*c) for c in p["coords"]]) for p in net.pieces]
    ptree = shapely.STRtree(piece_lines)
    idx, d_open = ptree.query_nearest(polys, return_distance=True, all_matches=False)
    snap_piece = np.full(len(b), -1)
    snap_piece[idx[0]] = idx[1]
    d_truck = np.full(len(b), np.inf)
    d_truck[idx[0]] = d_open
    all_lines = [LineString([to_xy(*c) for c in w["coords"]]) for w in net.ways]
    atree = shapely.STRtree(all_lines)
    idx2, d_any = atree.query_nearest(polys, return_distance=True, all_matches=False)
    any_way = np.full(len(b), -1)
    any_way[idx2[0]] = idx2[1]
    d_anyroad = np.full(len(b), np.inf)
    d_anyroad[idx2[0]] = d_any
    closed_reason = np.array([net.ways[w]["blocked"] or "" if w >= 0 else "" for w in any_way], dtype=object)

    # --- дворовые и узкие участки
    lm_cfg = cfg["lastmile"]
    res_bxy = bxy[b["is_res_type"].to_numpy()]
    mid = np.array([to_xy(*p["coords"][len(p["coords"]) // 2]) for p in net.pieces])
    n_res_near = KDTree(res_bxy).query_radius(mid, r=lm_cfg["yard_near_res_buildings_m"], count_only=True) \
        if len(res_bxy) else np.zeros(len(mid))
    in_res_lu = np.zeros(len(mid), bool)
    if osm["res_landuse"]:
        rtree = shapely.STRtree(osm["res_landuse"])
        hit = rtree.query(shapely.points(mid), predicate="intersects")
        in_res_lu[np.unique(hit[0])] = True
    service = np.isin(net.p_hw, ["service", "living_street"])
    yard_piece = service & ((n_res_near >= lm_cfg["yard_min_res_buildings"]) | in_res_lu)
    width = np.array([(lambda v: v if v is not None else 99)(_num(t.get("width"))) for t in net.p_tags])
    narrow_piece = (width < lm_cfg["narrow_width_m"]) | np.array([t.get("service") in ("alley", "driveway")
                                                                   for t in net.p_tags])
    log("  последняя миля…")
    lm = edge_lastmile(net, yard_piece, narrow_piece)

    # --- по зданию: лучшее ребро участка
    rows = {f: np.full(len(b), np.nan) for f in FEATURES}
    exit_names = cfg["exits"]["names"]
    t_exit = {k: np.full(len(b), np.inf) for k in exit_names}
    access_edge = np.full(len(b), -1)
    for i in range(len(b)):
        p = snap_piece[i]
        if p < 0:
            continue
        es = net.piece_edges[p]
        for k in exit_names:
            o = min(trees[k]["to"][0][e] for e in es)
            f = min(trees[k]["from"][0][e] for e in es)
            t_exit[k][i] = (o + f) / 2 if np.isfinite(o) and np.isfinite(f) else np.inf
        ok = [e for e in es if lm["ok"][e]]
        access_edge[i] = min(ok, key=lambda e: lm["time"][e]) if ok else es[0]
    for k in exit_names:
        rows["t_" + EXIT_KEY[k]] = np.where(np.isfinite(t_exit[k]), t_exit[k], NO_PATH_MIN)
    tmat = np.column_stack([rows["t_" + EXIT_KEY[k]] for k in exit_names])
    srt = np.sort(tmat, axis=1)
    rows["t_best"], rows["t_backup"] = srt[:, 0], srt[:, 1]
    rows["n_exits_20"] = (tmat <= 20).sum(axis=1)

    ae = access_edge
    has = (ae >= 0) & (d_truck <= lm_cfg["max_snap_m"])
    has_path = has & np.where(ae >= 0, lm["ok"][np.maximum(ae, 0)], False)
    g = lambda k: np.where(has_path, lm[k][np.maximum(ae, 0)], np.nan)
    rows["lm_has_path"] = has_path.astype(float)
    rows["lm_len_m"] = np.where(has_path, g("len") + d_truck, 3000.0)
    rows["lm_time_min"] = np.where(has_path, g("time"), NO_PATH_MIN)
    rows["lm_res_share"] = np.where(has_path, (g("res") + g("yard")) / np.maximum(g("len"), 1), 1.0)
    rows["lm_yard_m"] = np.where(has_path, g("res") + g("yard"), 3000.0)
    rows["lm_turns"] = np.where(has_path, g("turns"), 20)
    rows["lm_oneway_n"] = np.where(has_path, g("oneway"), 10)
    rows["lm_narrow_m"] = np.where(has_path, g("narrow"), 1000.0)
    deg = net.degree
    dead = np.array([(deg[net.pieces[p]["u"]] == 1 or deg[net.pieces[p]["v"]] == 1) if p >= 0 else True
                     for p in snap_piece])
    rows["lm_dead_end"] = dead.astype(float)
    rows["d_truck_road_m"] = np.minimum(d_truck, 2000.0)
    rows["d_closed_road_gap_m"] = np.clip(np.minimum(d_truck, 2000) - d_anyroad, 0, 2000)

    # --- существенные ограничения рядом (мосты, высота, масса, запреты)
    MINOR = ("тип дороги", "грунт")
    rp = np.array([to_xy(*c) for w in net.ways if w["blocked"] and not w["blocked"].startswith(MINOR)
                   for c in w["coords"]])
    r_reason = np.array([w["blocked"] for w in net.ways if w["blocked"] and not w["blocked"].startswith(MINOR)
                         for c in w["coords"]], dtype=object)
    rtree_ = KDTree(rp)
    dd, ii = rtree_.query(bxy, k=1)
    rows["restr_dist_m"] = np.minimum(dd[:, 0], 3000)
    restr_reason = r_reason[ii[:, 0]]
    # ограничения в 1 км: считаем разные дороги, а не точки
    r_way = np.array([w["id"] for w in net.ways if w["blocked"] and not w["blocked"].startswith(MINOR)
                      for c in w["coords"]])
    rows["restr_n_1km"] = np.array([len(set(r_way[j])) for j in rtree_.query_radius(bxy, r=1000)], float)

    # --- окружение
    log("  окружение…")
    all_tree = KDTree(bxy)
    is_res = b["is_res_type"].to_numpy()
    res_tree = KDTree(bxy[is_res]) if is_res.any() else None
    for r in (100, 200, 500):
        n_all = all_tree.query_radius(bxy, r=r, count_only=True) - 1
        n_res = (res_tree.query_radius(bxy, r=r, count_only=True) if res_tree is not None else 0) - is_res
        rows[f"res_n_{r}"] = n_res.astype(float)
        rows[f"res_share_{r}"] = np.where(n_all > 0, n_res / np.maximum(n_all, 1), 0.0)
    poi = osm["poi"]
    sch = np.r_[poi.loc[poi.kind == "school", ["x", "y"]].to_numpy().reshape(-1, 2),
                bxy[b["building"].isin(["school", "kindergarten"]).to_numpy()]]
    hos = np.r_[poi.loc[poi.kind == "hospital", ["x", "y"]].to_numpy().reshape(-1, 2),
                bxy[b["building"].isin(["hospital"]).to_numpy()]]
    rows["d_school_m"] = np.minimum(KDTree(sch).query(bxy, k=1)[0][:, 0], 3000) if len(sch) else 3000.0
    rows["d_hospital_m"] = np.minimum(KDTree(hos).query(bxy, k=1)[0][:, 0], 5000) if len(hos) else 5000.0
    mtree = KDTree(mid)
    rows["road_km_500"] = np.array([net.p_len[j].sum() / 1000 for j in mtree.query_radius(bxy, r=500)])
    cx, cy = to_xy(*CENTER)
    rows["d_center_km"] = np.hypot(bxy[:, 0] - cx, bxy[:, 1] - cy) / 1000

    # --- достижимость города
    log("  достижимость города (центры спроса)…")
    cr = cfg["city_reach"]
    housing = (~b["building"].isin(["industrial", "warehouse", "hangar", "garages", "garage", "shed", "roof",
                                    "storage_tank", "greenhouse", "ruins", "construction", "manufacture",
                                    "factory", "service"]).to_numpy()) & (b["area_m2"].to_numpy() <= 5000)
    in_ind = np.zeros(len(b), bool)
    if osm["industrial"]:
        itree = shapely.STRtree([p["geom"] for p in osm["industrial"]])
        hit = itree.query(shapely.points(bxy), predicate="intersects")
        in_ind[np.unique(hit[0])] = True
    housing &= ~in_ind
    shops = poi.loc[poi.kind == "shop", ["x", "y"]].to_numpy().reshape(-1, 2)
    dem_xy = np.r_[bxy[housing], shops]
    km = KMeans(n_clusters=cr["n_centers"], n_init=3, random_state=cfg["random_state"]).fit(dem_xy)
    centers = km.cluster_centers_
    weights = np.bincount(km.labels_, minlength=len(centers)).astype(float)
    cpi, _ = ptree.query_nearest(shapely.points(centers), return_distance=True, all_matches=False)
    c_piece = np.full(len(centers), -1)
    c_piece[cpi[0]] = cpi[1]
    targets = [{net.pieces[p]["u"], net.pieces[p]["v"]} for p in c_piece]
    wsum = weights.sum()
    e_mean = np.zeros(net.E)
    e_s15, e_s25 = np.zeros(net.E), np.zeros(net.E)
    for i0, M in net.many_to(targets, batch=25):
        w = weights[i0:i0 + len(M)][:, None]
        Mf = np.where(np.isfinite(M), M, NO_PATH_MIN)
        e_mean += (Mf * w).sum(axis=0)
        e_s15 += ((M <= cr["minutes_near"]) * w).sum(axis=0)
        e_s25 += ((M <= cr["minutes_far"]) * w).sum(axis=0)
    e_mean /= wsum
    e_s15 /= wsum
    e_s25 /= wsum
    cp, _ = ptree.query_nearest(Point(cx, cy), return_distance=True)
    cpp = net.pieces[int(np.atleast_1d(cp)[0])]
    c_to, _ = net.tree_to({cpp["u"], cpp["v"]})
    for f in ("city_mean_min", "city_center_min", "city_share_15", "city_share_25"):
        rows[f] = np.full(len(b), np.nan)
    for i in range(len(b)):
        p = snap_piece[i]
        if p < 0:
            continue
        es = net.piece_edges[p]
        rows["city_mean_min"][i] = min(e_mean[e] for e in es)
        rows["city_center_min"][i] = min(c_to[e] for e in es)
        rows["city_share_15"][i] = max(e_s15[e] for e in es)
        rows["city_share_25"][i] = max(e_s25[e] for e in es)
    rows["city_center_min"] = np.where(np.isfinite(rows["city_center_min"]), rows["city_center_min"], NO_PATH_MIN)
    rows["city_mean_min"] = np.where(np.isfinite(rows["city_mean_min"]), rows["city_mean_min"], NO_PATH_MIN)

    # --- ж/д и свободное место
    log("  ж/д и свободное место…")
    rails = osm["rail"]
    if rails:
        rl = shapely.STRtree([LineString(r) for r in rails])
        _, drail = rl.query_nearest(shapely.points(bxy), return_distance=True, all_matches=False)
        rows["d_rail_m"] = np.minimum(drail, 5000)
    else:
        rows["d_rail_m"] = np.full(len(b), 5000.0)
    st = poi.loc[poi.kind == "rail_station", ["x", "y"]].to_numpy().reshape(-1, 2)
    rows["d_rail_station_m"] = np.minimum(KDTree(st).query(bxy, k=1)[0][:, 0], 8000) if len(st) else 8000.0
    rows["free_share_30"] = free_space(polys, 30)

    X = pd.DataFrame(rows)
    side = pd.DataFrame({
        "snap_piece": snap_piece, "access_edge": access_edge, "d_anyroad_m": d_anyroad,
        "closed_reason": closed_reason, "restr_reason": restr_reason, "in_industrial": in_ind,
        "yard_landuse": _inside(osm["res_landuse"], bxy)})
    for k in exit_names:   # «нет пути» — отдельно, чтобы в карточке не писать 90 минут
        side["path_" + EXIT_KEY[k]] = np.isfinite(t_exit[k])
    extra = {"exits": exits, "trees": trees, "centers": centers, "center_weights": weights,
             "yard_piece": yard_piece, "polys": polys}
    log("  признаки готовы")
    return X, side, extra


def _inside(polys, xy):
    out = np.zeros(len(xy), bool)
    if polys:
        t = shapely.STRtree(polys)
        hit = t.query(shapely.points(xy), predicate="intersects")
        out[np.unique(hit[0])] = True
    return out


def free_space(polys, r):
    """Доля площади кольца r метров вокруг здания, не занятая другими зданиями (место для разворота фуры)."""
    polys = shapely.make_valid(np.asarray(polys))
    ring = shapely.difference(shapely.buffer(polys, r, quad_segs=4), polys)
    ring_area = shapely.area(ring)
    tree = shapely.STRtree(polys)
    a, o = tree.query(ring, predicate="intersects")
    m = a != o
    a, o = a[m], o[m]
    inter = shapely.area(shapely.intersection(ring[a], polys[o]))
    busy = np.bincount(a, weights=inter, minlength=len(polys))
    return np.clip(1 - busy / np.maximum(ring_area, 1), 0, 1)


def cluster_counts(bxy, positive, radii=(500, 1000)):
    """Сколько складов/производств рядом (без самого здания). В модель НЕ идёт (это та же метка у соседей),
    используется только в формуле профиля «ж/д и кластер»."""
    out = {}
    tree = KDTree(bxy[positive]) if positive.any() else None
    for r in radii:
        n = tree.query_radius(bxy, r=r, count_only=True) if tree is not None else np.zeros(len(bxy))
        out[f"wh_n_{r}"] = (n - positive).astype(float)
    return out


def _num(v):
    if v is None:
        return None
    try:
        return float(str(v).split()[0].replace(",", "."))
    except ValueError:
        return None
