"""Данные OpenStreetMap, которых нет в базе дорог дата-инженера: здания, промзоны и склады, ж/д,
Волга (чтобы отделить Саратов от Энгельса), школы/детсады/больницы, магазины, жилые кварталы.

Скачивание (бесплатный Overpass API, без ключей):  python src/osm_data.py   (--force — перекачать)
Каждый запрос сохраняется в ml/data/osm/osm_<имя>.json; уже скачанное не повторяется.
"""
import json, math, os, sys, time, urllib.parse, urllib.request

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paths import OSM  # noqa: E402

BBOX = "51.35,45.70,51.82,46.35"  # юг, запад, север, восток — как в data_engineering/data/raw/query.overpassql
QUERIES = {
    "objects": f"""[out:json][timeout:180];
(
  nwr["building"="warehouse"]({BBOX});
  nwr["industrial"~"^(warehouse|logistics|distribution|depot)$"]({BBOX});
  nwr["shop"="wholesale"]({BBOX});
  nwr["landuse"="industrial"]({BBOX});
  nwr["man_made"="works"]({BBOX});
);
out tags geom;""",
    "rail": f"""[out:json][timeout:180];
way["railway"~"^(rail|narrow_gauge)$"]({BBOX});
out tags geom;""",
    "volga": f"""[out:json][timeout:180];
way["waterway"="river"]["name"="Волга"]({BBOX});
out tags geom;""",
    # школы, детсады, больницы (санитарные ограничения), магазины (центры спроса), ж/д станции
    "poi": f"""[out:json][timeout:180];
(
  nwr["amenity"~"^(school|kindergarten|hospital|clinic)$"]({BBOX});
  node["shop"]({BBOX});
  nwr["railway"~"^(station|halt|yard|cargo_terminal)$"]({BBOX});
);
out tags center;""",
    # жилые кварталы — только для правил и карточки (не признак модели)
    "landuse_res": f"""[out:json][timeout:240];
(
  way["landuse"="residential"]({BBOX});
  relation["landuse"="residential"]({BBOX});
);
out tags geom;""",
}
SERVERS = ["https://overpass-api.de/api/interpreter",
           "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
           "https://overpass.kumi.systems/api/interpreter"]
USER_AGENT = "RealEstate3D-warehouse-study/2.0 (student project, Saratov)"

LAT0 = 51.55
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110574   # метров в градусе


def to_xy(lon, lat):
    return lon * KX, lat * KY


# ---------------------------------------------------------------- скачивание
def fetch(query):
    for attempt in range(3):
        for url in SERVERS:
            try:
                req = urllib.request.Request(url, data=urllib.parse.urlencode({"data": query}).encode(),
                                             headers={"User-Agent": USER_AGENT})
                return json.load(urllib.request.urlopen(req, timeout=260))["elements"]
            except Exception as e:  # сервер занят — пробуем следующий
                print("  не удалось", url, "—", e, flush=True)
        time.sleep(15)
    raise SystemExit("Overpass недоступен, попробуйте позже")


BUILD_BBOX = (51.40, 45.75, 51.72, 46.20)   # здания Саратова (Энгельс отсекается по Волге)
BUILD_TILES = 4


def fetch_buildings(force=False):
    raw_dir = OSM / "raw_buildings"
    raw_dir.mkdir(exist_ok=True)
    s, w, n, e = BUILD_BBOX
    dy, dx = (n - s) / BUILD_TILES, (e - w) / BUILD_TILES
    for i in range(BUILD_TILES):
        for j in range(BUILD_TILES):
            path = raw_dir / f"tile_{i}_{j}.json"
            if path.exists() and not force:
                continue
            bb = f"{s + i * dy:.4f},{w + j * dx:.4f},{s + (i + 1) * dy:.4f},{w + (j + 1) * dx:.4f}"
            part = fetch(f'[out:json][timeout:180];way["building"]({bb});out tags geom;')
            json.dump({"elements": part}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
            print(f"  здания, плитка {i},{j}: {len(part)}", flush=True)
    # здания-мультиполигоны (крупные ТЦ, заводы): в OSM это отношения, а не простые контуры
    path = raw_dir / "relations.json"
    if not path.exists() or force:
        part = fetch(f'[out:json][timeout:180];relation["building"]({s},{w},{n},{e});out body geom;')
        json.dump({"elements": part}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  здания-мультиполигоны: {len(part)}", flush=True)


def fetch_all(force=False):
    for name, q in QUERIES.items():
        path = OSM / f"osm_{name}.json"
        if path.exists() and not force:
            print(f"{name}: уже скачано", flush=True)
            continue
        part = fetch(q)
        json.dump({"elements": part}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"{name}: {len(part)} объектов", flush=True)
    fetch_buildings(force)


# ---------------------------------------------------------------- правый берег Волги
class RightBank:
    """Правый берег Волги (Саратов). Река в OSM нарисована по течению (с севера на юг),
    правый берег — справа от направления течения."""

    def __init__(self, river_xy):
        from sklearn.neighbors import KDTree
        self.seg = np.array([[a[0], a[1], b[0], b[1]] for a, b in zip(river_xy, river_xy[1:])])
        self.tree = KDTree((self.seg[:, :2] + self.seg[:, 2:]) / 2)

    def contains(self, xy):
        xy = np.atleast_2d(xy)
        _, idx = self.tree.query(xy, k=8)
        s = self.seg[idx]                                   # (n, 8, 4)
        ax, ay, bx, by = s[..., 0], s[..., 1], s[..., 2], s[..., 3]
        px, py = xy[:, :1], xy[:, 1:2]
        t = np.clip(((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / ((bx - ax) ** 2 + (by - ay) ** 2 + 1e-9), 0, 1)
        d = np.hypot(ax + t * (bx - ax) - px, ay + t * (by - ay) - py)
        k = np.argmin(d, axis=1)
        r = np.arange(len(xy))
        cross = (bx[r, k] - ax[r, k]) * (xy[:, 1] - ay[r, k]) - (by[r, k] - ay[r, k]) * (xy[:, 0] - ax[r, k])
        return cross < 0


def _elements(name):
    path = OSM / f"osm_{name}.json"
    if not path.exists():
        return []
    return json.load(open(path, encoding="utf-8"))["elements"]


def load_city():
    for e in _elements("volga"):
        if e.get("tags", {}).get("waterway") == "river" and e.get("geometry"):
            return RightBank([to_xy(g["lon"], g["lat"]) for g in e["geometry"]])
    return None


def _polygons(el):
    from shapely.geometry import LineString, Polygon
    from shapely.ops import polygonize
    out = []
    if el["type"] == "way" and el.get("geometry"):
        pts = [to_xy(g["lon"], g["lat"]) for g in el["geometry"]]
        if len(pts) >= 4 and pts[0] == pts[-1]:
            out.append(Polygon(pts))
    elif el["type"] == "relation":
        lines = [LineString([to_xy(g["lon"], g["lat"]) for g in m["geometry"]])
                 for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")
                 and len(m["geometry"]) > 1]
        out += list(polygonize(lines))
    return [g for g in out if g.is_valid and g.area > 0]


def load_industrial(city=None):
    """Промзоны и складские территории (landuse=industrial, склады, оптовые базы) — полигоны в метрах."""
    from shapely.geometry import Point
    polys = []
    for e in _elements("objects"):
        t = e.get("tags", {})
        kind = "склад" if (t.get("building") == "warehouse" or t.get("industrial") in
                           ("warehouse", "logistics", "distribution", "depot") or t.get("shop") == "wholesale") \
            else "промзона"
        geoms = _polygons(e)
        if e["type"] == "node":
            geoms = [Point(to_xy(e["lon"], e["lat"])).buffer(30)]
        for g in geoms:
            polys.append({"geom": g, "kind": kind, "name": t.get("name", ""), "area_ha": g.area / 1e4})
    if city is not None and polys:
        keep = city.contains(np.array([p["geom"].representative_point().coords[0] for p in polys]))
        polys = [p for p, k in zip(polys, keep) if k]
    return polys


def load_residential_landuse():
    out = []
    for e in _elements("landuse_res"):
        out += _polygons(e)
    return out


def load_rail():
    lines = [[to_xy(g["lon"], g["lat"]) for g in e.get("geometry", [])] for e in _elements("rail")]
    return [l for l in lines if len(l) > 1]


def load_poi():
    """Школы/детсады/больницы, магазины, ж/д станции: DataFrame kind, x, y, name."""
    rows = []
    for e in _elements("poi"):
        t = e.get("tags", {})
        c = e.get("center") or ({"lon": e["lon"], "lat": e["lat"]} if "lon" in e else None)
        if not c:
            continue
        if t.get("amenity") in ("school", "kindergarten"):
            kind = "school"
        elif t.get("amenity") in ("hospital", "clinic"):
            kind = "hospital"
        elif t.get("railway") in ("station", "halt", "yard", "cargo_terminal"):
            kind = "rail_station"
        elif t.get("shop"):
            kind = "shop"
        else:
            continue
        x, y = to_xy(c["lon"], c["lat"])
        rows.append({"kind": kind, "x": x, "y": y, "name": t.get("name", "")})
    return pd.DataFrame(rows, columns=["kind", "x", "y", "name"])


# ---------------------------------------------------------------- здания
RES_TYPES = {"apartments", "house", "residential", "detached", "semidetached_house", "terrace", "dormitory",
             "bungalow", "cabin", "farm"}
WAREHOUSE_TYPES = {"warehouse", "industrial", "hangar", "storage", "manufacture", "factory"}
BUILDING_RU = {"apartments": "многоквартирный дом", "house": "частный дом", "detached": "частный дом",
               "semidetached_house": "дом на две семьи", "residential": "жилой дом", "industrial": "промышленное здание",
               "warehouse": "склад", "commercial": "коммерческое здание", "retail": "торговое здание",
               "office": "офисное здание", "garages": "гаражи", "garage": "гараж", "service": "служебное здание",
               "school": "школа", "kindergarten": "детский сад", "hospital": "больница", "yes": "здание (тип не указан)",
               "construction": "строится", "supermarket": "супермаркет", "hangar": "ангар", "shed": "сарай",
               "university": "вуз", "college": "колледж", "church": "храм", "hotel": "гостиница",
               "dormitory": "общежитие", "manufacture": "производство", "public": "общественное здание",
               "terrace": "таунхаус", "roof": "навес", "storage_tank": "резервуар", "greenhouse": "теплица",
               "ruins": "руины", "kiosk": "киоск", "government": "госучреждение", "storage": "склад",
               "factory": "завод", "train_station": "вокзал", "transportation": "транспортное здание",
               "sports_hall": "спортзал", "civic": "общественное здание"}


def compact_buildings():
    """Из сырых плиток Overpass — таблица зданий: id OSM, центр, площадь, тип, адрес, имя, контур (точность 10 см)."""
    raw_dir = OSM / "raw_buildings"
    seen, rows = set(), []
    for f in sorted(os.listdir(raw_dir)):
        for el in json.load(open(raw_dir / f, encoding="utf-8"))["elements"]:
            if el.get("type") == "relation":
                el = _relation_outline(el)
                if el is None:
                    continue
            if el["id"] in seen or len(el.get("geometry", [])) < 4:
                continue
            seen.add(el["id"])
            t = el.get("tags", {})
            pts = [(g["lon"], g["lat"]) for g in el["geometry"]]
            xy = [to_xy(lo, la) for lo, la in pts]
            area = abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(xy, xy[1:]))) / 2
            cx = sum(p[0] for p in pts[:-1]) / (len(pts) - 1)
            cy = sum(p[1] for p in pts[:-1]) / (len(pts) - 1)
            street = t.get("addr:street") or t.get("addr:place") or ""
            house = t.get("addr:housenumber") or ""
            # контур без искажений: убираем только точки, которые сдвигают стену меньше чем на 0.3 м
            from shapely.geometry import Polygon as _P
            sp = _P(xy).simplify(0.3, preserve_topology=True)
            poly = [(x / KX, y / KY) for x, y in sp.exterior.coords] if sp.is_valid and not sp.is_empty else pts
            flat, px, py = [], 0, 0
            for lo, la in poly:   # точность 1e-6° ≈ 10 см
                ix, iy = round(lo * 1e6), round(la * 1e6)
                flat += [ix - px, iy - py]
                px, py = ix, iy
            rows.append([el["id"], round(cx, 6), round(cy, 6), round(area), t.get("building", "yes"), street, house,
                         t.get("name", ""), t.get("amenity", "") or t.get("shop", ""), flat])
    cols = ["osm_id", "lon", "lat", "area_m2", "building", "street", "house", "name", "amenity", "poly"]
    out = OSM / "buildings.json"
    json.dump({"columns": cols, "rows": rows}, open(out, "w", encoding="utf-8"), ensure_ascii=False,
              separators=(",", ":"))
    print(f"здания: {len(rows)} → {out} ({out.stat().st_size / 1e6:.1f} МБ)", flush=True)


def _relation_outline(el):
    """Мультиполигон здания → самый большой внешний контур в виде «как у простого здания»."""
    from shapely.geometry import LineString
    from shapely.ops import polygonize
    lines = [LineString([(g["lon"], g["lat"]) for g in m["geometry"]]) for m in el.get("members", [])
             if m.get("role") == "outer" and m.get("geometry") and len(m["geometry"]) > 1]
    polys = list(polygonize(lines))
    if not polys:
        return None
    big = max(polys, key=lambda p: p.area)
    return {"id": -el["id"], "type": "relation", "tags": el.get("tags", {}),   # минус — это отношение OSM, не контур
            "geometry": [{"lon": x, "lat": y} for x, y in big.exterior.coords]}


def decode_poly(flat):
    pts, x, y = [], 0, 0
    for i in range(0, len(flat), 2):
        x, y = x + flat[i], y + flat[i + 1]
        pts.append((x / 1e6, y / 1e6))
    return pts


def load_buildings(city=None):
    path = OSM / "buildings.json"
    if not path.exists():
        compact_buildings()
    d = json.load(open(path, encoding="utf-8"))
    b = pd.DataFrame(d["rows"], columns=d["columns"])
    b["x"], b["y"] = b["lon"] * KX, b["lat"] * KY
    if city is not None:
        b = b[city.contains(b[["x", "y"]].to_numpy())].reset_index(drop=True)
    b["addr"] = np.where((b["street"] != "") & (b["house"] != ""), b["street"] + ", " + b["house"], b["street"])
    b["is_res_type"] = b["building"].isin(RES_TYPES)
    b["type_ru"] = b["building"].map(lambda t: BUILDING_RU.get(t, t))
    return b


if __name__ == "__main__":
    fetch_all("--force" in sys.argv)
    compact_buildings()
