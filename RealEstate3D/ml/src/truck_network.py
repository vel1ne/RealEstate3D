"""Граф дорог Саратова для фуры + время в пути по модели загруженности (Colab «модель дорог»).

Источник дорог: база дата-инженера data_engineering/data/processed/saratov_roads.sqlite (OSM 2026-10-27),
открывается только на чтение.
Скорости: формула и коэффициенты из Colab-модели коллеги
    Roads(coef1=0.85, link_speed=5, coef2=0.75, coef3=0.95, coef4=0.9, graf_coef=1, plus1=1, plus2=1, plus3=0.5)
Маршруты: Дейкстра по рёбрам (а не по узлам), чтобы учесть штрафы за поворот и запреты поворотов.
Быстрый вариант: «граф переходов между рёбрами» + scipy.sparse.csgraph.dijkstra (сотни деревьев за минуты).
"""
import json, math, sqlite3
from collections import defaultdict

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

# ---------- параметры модели загруженности (из Colab) ----------
COEF1, LINK_SPEED, COEF2, COEF3, COEF4 = 0.85, 5, 0.75, 0.95, 0.9
TURN_UTURN, TURN_LEFT, TURN_RIGHT = 1.0, 1.0, 0.5          # минуты
SPEED_MAP = {"service": 20, "residential": 20, "unclassified": 60, "tertiary": 60, "secondary": 60,
             "primary": 60, "trunk": 90, "motorway": 110, "secondary_link": 20, "tertiary_link": 20,
             "primary_link": 20, "trunk_link": 20, "motorway_link": 20, "living_street": 20,
             "construction": 40, "track": 20}
NAMED_SPEED = {"RU:urban": 60, "RU:rural": 90, "RU:living_street": 5, "RU:motorway": 110}

# ---------- параметры фуры ----------
TRUCK = {"height": 4.0, "weight": 40.0, "max_speed": 70}
TRUCK_FORBIDDEN_HIGHWAY = {"track", "living_street", "construction", "proposed"}
BAD_SURFACE = {"ground", "dirt", "grass", "mud", "sand", "earth"}
SLOW_SURFACE = {"unpaved", "gravel", "compacted", "fine_gravel", "pebblestone"}
BLOCKING_BARRIERS = {"block", "bollard", "chain", "log", "debris", "planter", "jersey_barrier", "cycle_barrier",
                     "fence", "tree", "kissing_gate", "hampshire_gate", "height_restrictor", "wicket_gate", "kerb"}
ARTERIAL = {"trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link", "motorway",
            "motorway_link"}

# ручные ограничения, собранные нами раньше (ноутбук saratov_roads_v2, RESTRICTIONS)
MANUAL_RESTRICTIONS = [
    {"name": "Ж/д мост, 13-й/16-й Белоглинский проезд", "osm_ids": [30860720, 31784040], "maxheight": 2.5},
    {"name": "Саратовский мост", "osm_ids": [203336910, 197979709], "no_trucks": True},
    {"name": "Большая Затонская под Саратовским мостом", "osm_ids": [30892532], "no_trucks": True},
    {"name": "Дублёр 50 лет Октября под мостами к Тракторной",
     "osm_ids": [866969149, 873832521, 873832513, 866969148], "maxheight": 3.5},
    {"name": "Мост на Дровяной (у Степана Разина)", "osm_ids": [777098539], "maxweight": 10},
    {"name": "Мост между 50 лет Октября и Шехурдина", "osm_ids": [867769438], "maxweight": 20},
]

LAT0 = 51.55
KX, KY = 111320 * math.cos(math.radians(LAT0)), 110574  # метры на градус


def to_xy(lon, lat):
    return lon * KX, lat * KY


def num(v):
    if v is None:
        return None
    try:
        return float(str(v).split()[0].replace(",", "."))
    except ValueError:
        return None


def car_speed(tags, highway):
    """Скорость «с учётом пробок» по формуле из Colab."""
    ms = tags.get("maxspeed")
    s = NAMED_SPEED.get(ms) if ms in NAMED_SPEED else num(ms)
    if s is None:
        s = SPEED_MAP.get(highway, 20)
    real = s * COEF1
    if highway in ("primary_link", "secondary_link", "tertiary_link"):
        real = LINK_SPEED
    if tags.get("surface") in ("unpaved", "ground", "gravel") and s == 60:
        real = 20
    oneway = tags.get("oneway", "no")
    lanes = num(tags.get("lanes"))
    if highway in ("primary", "secondary", "tertiary", "unclassified"):
        real *= COEF2
        if lanes is not None and lanes <= 4 and oneway == "no":
            real *= COEF3
        if lanes == 1 and oneway in ("yes", "-1"):
            real *= COEF4
    return max(real, 1.0)


class TruckNetwork:
    def __init__(self, sqlite_path):
        self.why_blocked = {}           # osm_way_id -> причина, почему фуре нельзя
        self._load(sqlite_path)
        self._build()
        self._line_graph()

    # ---------------- загрузка (база инженера — только чтение) ----------------
    def _load(self, path):
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        rows = con.execute("select osm_way_id, name, ref, highway, tags_json, node_ids_json, geometry_geojson, "
                           "maxheight_m, maxweight_t from road_segment").fetchall()
        self.dataset_key = con.execute("select dataset_key from dataset limit 1").fetchone()[0]
        self.ways = []
        manual = {o: r for r in MANUAL_RESTRICTIONS for o in r["osm_ids"]}
        for wid, name, ref, hw, tj, nj, gj, mh, mw in rows:
            tags = json.loads(tj)
            why = self._truck_block_reason(hw, tags, mh, mw, manual.get(wid))
            self.ways.append({"id": wid, "name": name, "ref": ref, "highway": hw, "tags": tags,
                              "nodes": json.loads(nj), "coords": json.loads(gj)["coordinates"], "blocked": why})
            if why:
                self.why_blocked[wid] = why
        self.node_xy = {}
        for w in self.ways:
            for n, (lon, lat) in zip(w["nodes"], w["coords"]):
                self.node_xy[n] = (lon, lat)
        self.blocked_nodes = {}
        for nid, tj in con.execute("select osm_node_id, tags_json from point_constraint"):
            t = json.loads(tj)
            mh = num(t.get("maxheight"))
            if t.get("barrier") in BLOCKING_BARRIERS:
                self.blocked_nodes[nid] = f"препятствие: {t.get('barrier')}"
            elif t.get("access") == "no" or t.get("motor_vehicle") == "no" or t.get("hgv") == "no":
                self.blocked_nodes[nid] = "проезд закрыт"
            elif mh is not None and mh < TRUCK["height"]:
                self.blocked_nodes[nid] = f"высота {mh:g} м"
        self.turn_no, self.turn_only = set(), {}
        for tj, mj in con.execute("select tags_json, members_json from turn_restriction_raw"):
            t, members = json.loads(tj), json.loads(mj)
            kind = t.get("restriction") or t.get("restriction:hgv") or ""
            fr = [m["ref"] for m in members if m["role"] == "from" and m["type"] == "way"]
            to = [m["ref"] for m in members if m["role"] == "to" and m["type"] == "way"]
            via = [m["ref"] for m in members if m["role"] == "via" and m["type"] == "node"]
            if not (fr and to and via):
                continue
            if kind.startswith("no_"):
                self.turn_no.add((fr[0], via[0], to[0]))
            elif kind.startswith("only_"):
                self.turn_only[(fr[0], via[0])] = to[0]
        con.close()

    @staticmethod
    def _truck_block_reason(hw, tags, mh, mw, manual):
        if hw in TRUCK_FORBIDDEN_HIGHWAY:
            return f"тип дороги {hw}"
        for k in ("access", "vehicle", "motor_vehicle"):
            if tags.get(k) == "no":   # access=private не закрываем: так помечены и проезды на территорию складов
                return f"{k}=no"
        if tags.get("hgv") == "no" or tags.get("goods") == "no":
            return "грузовым запрещено (OSM)"
        if tags.get("surface") in BAD_SURFACE:
            return f"грунт ({tags.get('surface')})"
        h = num(tags.get("maxheight:hgv")) or mh
        if h is not None and h < TRUCK["height"]:
            return f"высота {h:g} м"
        wt = num(tags.get("maxweight:hgv")) or mw
        if wt is not None and wt < TRUCK["weight"]:
            return f"масса до {wt:g} т"
        if manual:
            if manual.get("no_trucks"):
                return f"{manual['name']}: грузовым запрещено"
            if manual.get("maxheight", 99) < TRUCK["height"]:
                return f"{manual['name']}: высота {manual['maxheight']} м"
            if manual.get("maxweight", 999) < TRUCK["weight"]:
                return f"{manual['name']}: масса до {manual['maxweight']} т"
        return None

    # ---------------- граф ----------------
    def _build(self):
        use = defaultdict(int)
        for w in self.ways:
            if not w["blocked"]:
                for n in set(w["nodes"]):
                    use[n] += 1
        self.pieces = []   # участки дорог между перекрёстками
        for wi, w in enumerate(self.ways):
            if w["blocked"]:
                continue
            nodes, coords = w["nodes"], w["coords"]
            start = 0
            for i in range(1, len(nodes)):
                if i == len(nodes) - 1 or use[nodes[i]] > 1:
                    pn, pc = nodes[start:i + 1], coords[start:i + 1]
                    if not any(n in self.blocked_nodes for n in pn):
                        xy = [to_xy(*c) for c in pc]
                        length = sum(math.dist(a, b) for a, b in zip(xy, xy[1:]))
                        self.pieces.append({"way": wi, "u": pn[0], "v": pn[-1], "coords": pc, "length": length})
                    start = i
        self.degree = defaultdict(int)
        for p in self.pieces:
            self.degree[p["u"]] += 1
            self.degree[p["v"]] += 1
        self.e_from, self.e_to, self.e_time, self.e_piece, self.e_rev, self.e_way = [], [], [], [], [], []
        self.e_oneway = []
        for pi, p in enumerate(self.pieces):
            w = self.ways[p["way"]]
            t = w["tags"]
            speed = min(car_speed(t, w["highway"]), TRUCK["max_speed"])
            if t.get("surface") in SLOW_SURFACE:
                speed = min(speed, 20)
            minutes = round(p["length"] / 1000 / speed * 60, 3)
            p["speed"] = speed
            ow = t.get("oneway", "no")
            if t.get("junction") in ("roundabout", "circular") and ow == "no":
                ow = "yes"
            if ow in ("yes", "true", "1"):
                dirs = [False]
            elif ow == "-1":
                dirs = [True]
            else:
                dirs = [False, True]
            for rev in dirs:
                self.e_from.append(p["v"] if rev else p["u"])
                self.e_to.append(p["u"] if rev else p["v"])
                self.e_time.append(minutes)
                self.e_piece.append(pi)
                self.e_rev.append(rev)
                self.e_way.append(w["id"])
                self.e_oneway.append(len(dirs) == 1)
        self.E = len(self.e_time)
        self.out_edges, self.in_edges = defaultdict(list), defaultdict(list)
        for e in range(self.E):
            self.out_edges[self.e_from[e]].append(e)
            self.in_edges[self.e_to[e]].append(e)
        self.piece_edges = defaultdict(list)
        for e in range(self.E):
            self.piece_edges[self.e_piece[e]].append(e)
        e_vin, e_vout = [], []
        for e in range(self.E):
            c = self.pieces[self.e_piece[e]]["coords"]
            if self.e_rev[e]:
                c = c[::-1]
            a, b = to_xy(*c[0]), to_xy(*c[1])
            y, z = to_xy(*c[-2]), to_xy(*c[-1])
            e_vout.append((b[0] - a[0], b[1] - a[1]))
            e_vin.append((z[0] - y[0], z[1] - y[1]))
        # курсы (градусы, округлены до 0.01) — те же числа уходят в карту, чтобы повороты считались одинаково
        self.e_hout = [round(math.degrees(math.atan2(v[1], v[0])), 2) for v in e_vout]
        self.e_hin = [round(math.degrees(math.atan2(v[1], v[0])), 2) for v in e_vin]
        self.p_len = np.array([p["length"] for p in self.pieces])
        self.p_hw = np.array([self.ways[p["way"]]["highway"] for p in self.pieces])
        self.p_tags = [self.ways[p["way"]]["tags"] for p in self.pieces]

    # ---------------- повороты ----------------
    def allowed(self, e1, e2):
        node = self.e_to[e1]
        w1, w2 = self.e_way[e1], self.e_way[e2]
        if (w1, node, w2) in self.turn_no:
            return False
        only = self.turn_only.get((w1, node))
        return only is None or only == w2

    def turn_cost(self, e1, e2):
        if e1 != e2 and self.e_piece[e1] == self.e_piece[e2]:
            return TURN_UTURN
        ang = (self.e_hout[e2] - self.e_hin[e1] + 180) % 360 - 180   # >0 — налево, <0 — направо
        if abs(ang) > 135:
            return TURN_UTURN
        if ang > 60:
            return TURN_LEFT
        if ang < -60:
            return TURN_RIGHT
        return 0.0

    # ---------------- граф переходов «ребро → ребро» ----------------
    def _line_graph(self):
        a, b, turn = [], [], []
        for n, ins in self.in_edges.items():
            outs = self.out_edges.get(n, [])
            for e in ins:
                for s in outs:
                    if self.allowed(e, s):
                        a.append(e)
                        b.append(s)
                        turn.append(self.turn_cost(e, s))
        self.t_a, self.t_b, self.t_turn = np.array(a), np.array(b), np.array(turn)
        self.et = np.array(self.e_time)
        self.e_piece_arr = np.array(self.e_piece)

    EPS = 1e-9   # scipy не любит рёбра нулевого веса

    def _solve(self, sources, forward, with_pred=False):
        """sources: список наборов узлов. forward=True — время ОТ источника до конца каждого ребра
        (как tree_from); False — время от начала каждого ребра ДО цели (как tree_to)."""
        E, k = self.E, len(sources)
        rows, cols, vals = [], [], []
        for i, nodes in enumerate(sources):
            v = E + i
            for n in nodes:
                for e in (self.out_edges.get(n, []) if forward else self.in_edges.get(n, [])):
                    rows.append(v)
                    cols.append(e)
                    vals.append(self.et[e] + self.EPS)
        if forward:   # переход e→s стоит поворот + время s
            r = np.r_[self.t_a, rows]
            c = np.r_[self.t_b, cols]
            w = np.r_[self.t_turn + self.et[self.t_b] + self.EPS, vals]
        else:         # обратный граф: s→e стоит поворот + время e
            r = np.r_[self.t_b, rows]
            c = np.r_[self.t_a, cols]
            w = np.r_[self.t_turn + self.et[self.t_a] + self.EPS, vals]
        m = csr_matrix((w, (r.astype(np.int64), c.astype(np.int64))), shape=(E + k, E + k))
        res = dijkstra(m, directed=True, indices=np.arange(E, E + k), return_predecessors=with_pred)
        if with_pred:
            d, p = res
            return d[:, :E], p[:, :E]
        return res[:, :E]

    def tree_to(self, target_nodes):
        """Время от начала каждого ребра до цели. nxt[e] — следующее ребро (-1 — дальше цель)."""
        d, p = self._solve([target_nodes], forward=False, with_pred=True)
        nxt = np.where(p[0] >= self.E, -1, p[0])
        nxt[p[0] < 0] = -1
        return d[0], nxt

    def tree_from(self, source_nodes):
        """Время от источника до конца каждого ребра. prv[e] — предыдущее ребро."""
        d, p = self._solve([source_nodes], forward=True, with_pred=True)
        prv = np.where(p[0] >= self.E, -1, p[0])
        prv[p[0] < 0] = -1
        return d[0], prv

    def many_to(self, targets, batch=25):
        """Время от каждого ребра до каждой из целей: генератор (индексы, матрица batch×E)."""
        for i in range(0, len(targets), batch):
            yield i, self._solve(targets[i:i + batch], forward=False)
