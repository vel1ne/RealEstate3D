"""Интерактивная карта оценки зданий под склад: ml/out/map/ (index.html, label.html) и один файл
ml/out/Карта складов Саратова.html.

Баллы всех зданий предрасчитаны в Python (build_model.py). В браузере: выбор профиля (смена весов),
тексты карточки (те же формулы, что scoring.py), маршруты фуры по графу и поиск по адресу.
Карта рисуется своим кодом на canvas (без Leaflet и других картографических библиотек):
подложка — обычные плитки OpenStreetMap, поверх — здания, окрашенные по баллу.
Запуск:  python src/make_map.py   (после build_model.py)
"""
import json, os, pickle, shutil, sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import features as F                              # noqa: E402
import scoring as sc                              # noqa: E402
from paths import DE_SQLITE, OUT  # noqa: E402
from build_model import RESULTS                   # noqa: E402

SINGLE_NAME = "Карта складов Саратова.html"


def i10(a, k=10):
    return [int(v) for v in np.round(np.asarray(a, dtype=float) * k)]


def build_data():
    S = pickle.load(open(RESULTS, "rb"))
    cfg, R = S["cfg"], S["R"]
    from truck_network import TruckNetwork
    net = TruckNetwork(DE_SQLITE)
    exits = F.find_exits(net, cfg["exits"]["names"])

    node_index = {}

    def ni(n):
        if n not in node_index:
            node_index[n] = len(node_index)
        return node_index[n]

    pieces = []
    for p in net.pieces:
        flat, px, py = [], 0, 0
        for lon, lat in p["coords"]:
            ix, iy = round(lon * 1e5), round(lat * 1e5)
            flat += [ix - px, iy - py]
            px, py = ix, iy
        pieces.append(flat)
    # граф компактно: по участку — узлы концов, время (×1000), дорога, направления (0 — оба, 1 — прямо, 2 — обратно)
    way_index = {}
    dirs = {}
    for e in range(net.E):
        dirs.setdefault(net.e_piece[e], set()).add(net.e_rev[e])
    pc = {"u": [], "v": [], "t": [], "w": [], "d": []}
    for pi, p in enumerate(net.pieces):
        wid = net.ways[p["way"]]["id"]
        way_index.setdefault(wid, len(way_index))
        ds = dirs.get(pi, set())
        pc["u"].append(ni(p["u"]))
        pc["v"].append(ni(p["v"]))
        pc["t"].append(int(round(net.e_time[net.piece_edges[pi][0]] * 1000)) if pi in dirs else 0)
        pc["w"].append(way_index[wid])
        pc["d"].append(0 if ds == {False, True} else 1 if ds == {False} else 2 if ds == {True} else 3)
    turn_no = [[way_index[a], ni(n), way_index[b]] for a, n, b in net.turn_no
               if a in way_index and b in way_index and n in node_index]
    turn_only = [[way_index[a], ni(n), way_index[b]] for (a, n), b in net.turn_only.items()
                 if a in way_index and b in way_index and n in node_index]
    MAINHW = {"motorway", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link", "tertiary"}

    reasons = {"": 0}
    ri = lambda s: reasons.setdefault(s or "", len(reasons))
    types, streets = {}, {}
    ti = lambda s: types.setdefault(s, len(types))
    si = lambda s: streets.setdefault(s or "", len(streets))
    names = cfg["exits"]["names"]
    B = {
        "id": [int(v) for v in R["osm_id"]], "lat": R["lat"].round(6).tolist(), "lon": R["lon"].round(6).tolist(),
        "poly": R["poly"].tolist(), "addr": R["addr"].tolist(), "name": R["name"].tolist(),
        "type": [ti(t) for t in R["type_ru"]],
        "area": [int(v) for v in R["area_m2"]], "street": [si(s) for s in R["street_near"]],
        "ml": i10(R["ml"]), **{"s_" + k: i10(R["s_" + k]) for k in sc.PROFILE_PARTS},
        "mask": [int(v) for v in R["mask"]], "piece": [int(v) for v in R["snap_piece"]],
        "t": [[(int(round(v * 10)) if ok else -1) for v, ok in zip(R["t_" + F.EXIT_KEY[k]], R["path_" + F.EXIT_KEY[k]])]
              for k in names],
        "cc": i10(R["city_center_min"]), "cm": i10(R["city_mean_min"]), "cs": i10(R["city_share_25"], 1000),
        "lmh": [int(v) for v in R["lm_has_path"]], "lml": i10(R["lm_len_m"], 1), "lmy": i10(R["lm_yard_m"], 1),
        "lmt": i10(R["lm_turns"], 1), "de": [int(v) for v in R["lm_dead_end"]], "ow": i10(R["lm_oneway_n"], 1),
        "nw": i10(R["lm_narrow_m"], 1), "rd": i10(R["restr_dist_m"], 1), "rr": [ri(s) for s in R["restr_reason"]],
        "cg": i10(R["d_closed_road_gap_m"], 1), "cr": [ri(s) for s in R["closed_reason"]],
        "rn1": i10(R["res_n_100"], 1), "rn2": i10(R["res_n_200"], 1), "rs2": i10(R["res_share_200"], 1000),
        "ds": i10(R["d_school_m"], 1), "dr": i10(R["d_rail_m"], 1), "fr": i10(R["free_share_30"], 1000),
        "dc": i10(R["d_center_km"], 100), "wh": i10(R["wh_n_1000"], 1),
        **{"c_" + g: i10(R["c_" + g]) for g in F.FEATURE_GROUPS},
        "zone": [int(v) for v in R["zone"]], "cand": [int(v) for v in R["label_candidate"]],
    }
    Z = S["zones"]
    zones = [{"score": float(z["score"]), "mean": None if np.isnan(z["mean_score"]) else round(float(z["mean_score"]), 1),
              "nSuitable": int(z["n_suitable"]), "nGood": int(z["n_good"]), "nB": int(z["n_buildings"]),
              "area": float(z["area_ha"]), "streets": z["streets"], "best": int(z["best"]),
              "top3": [int(i) for i in z["top3"]], "cells": z["cells"]} for _, z in Z.iterrows()]
    s = S["summary"].set_index(["variant", "model"])
    final = S["report"]["Итоговая модель"]
    data = {
        "config": cfg, "featureGroupsRu": F.GROUP_RU, "partRu": sc.PART_RU, "ruleBits": sc.RULE_BITS,
        "pieces": pieces, "pieceMain": [1 if net.ways[p["way"]]["highway"] in MAINHW else 0 for p in net.pieces],
        "pc": pc, "turnNo": turn_no, "turnOnly": turn_only,
        "turnPenalty": {"uturn": 1.0, "left": 1.0, "right": 0.5},
        "exits": [{"name": k, "nodes": [node_index[n] for n in v["nodes"] if n in node_index],
                   "lonlat": v["lonlat"]} for k, v in exits.items()],
        "B": B, "types": list(types), "streets": list(streets), "reasons": list(reasons), "zones": zones,
        "center": list(F.CENTER),
        "model": {"name": final, "auc": round(float(s.loc[("A", final), "roc_auc"]), 3),
                  "ap": round(float(s.loc[("A", final), "ap"]), 3),
                  "formulaAuc": round(float(s.loc[("A", "formula"), "roc_auc"]), 3),
                  "formulaAp": round(float(s.loc[("A", "formula"), "ap"]), 3),
                  "expert": S["report"]["Экспертная разметка"], "date": S["report"]["Дата расчёта"]},
    }
    return data


F_RES = __import__("osm_data").RES_TYPES

# ====================================================================== общий JS (карта и разметка)
COMMON_JS = r"""
"use strict";
const D = window.MAP_DATA, CFG = D.config, B = D.B, NB = B.id.length;
const KX = 111320 * Math.cos(51.55 * Math.PI / 180), KY = 110574;
const distM = (la1, lo1, la2, lo2) => Math.hypot((la1 - la2) * KY, (lo1 - lo2) * KX);
const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
function decode(flat, k = 1e5) { const pts = []; let x = 0, y = 0;   // дороги — 1e-5°, контуры зданий — 1e-6°
  for (let i = 0; i < flat.length; i += 2) { x += flat[i]; y += flat[i + 1]; pts.push([y / k, x / k]); } return pts; }
const clip = (v, a = 0, b = 100) => Math.max(a, Math.min(b, v));
const f0 = v => String(Math.floor(v + 0.5));                                   // как scoring.f0
const f1 = v => (Math.floor(v * 10 + 0.5) / 10).toFixed(1).replace(".", ",");   // как scoring.f1
const r10 = v => String(Math.floor(v / 10 + 0.5) * 10);                        // как scoring.r10
const PARTS = ["exit", "city", "lastmile", "object", "rail_cluster"];
const GROUPS = ["exit", "lastmile", "env", "city", "infra"];
const BITS = D.ruleBits;
// ---------- балл профиля (как scoring.profile_score) ----------
function capOf(mask) { let cap = 100; for (const r of CFG.rules) if (mask & BITS[r.id]) cap = Math.min(cap, r.cap); return cap; }
function profileScore(i, profile) {
  const w = CFG.profiles[profile].weights; let acc = 0, wsum = 0;
  for (const k of PARTS) { acc += w[k] * (B["s_" + k][i] / 10); wsum += w[k]; }
  const a = CFG.alpha, total = a * (B.ml[i] / 10) + (1 - a) * (acc / wsum);
  return Math.min(total, capOf(B.mask[i]));
}
function badgeOf(total) { for (const b of CFG.badges) if (total >= b.min) return b; return CFG.badges[CFG.badges.length - 1]; }
function color(v) { const s = [[180,35,24],[232,163,23],[247,240,170],[65,171,93],[0,104,55]];
  const t = clip(v, 0, 100) / 25, i = Math.min(3, Math.floor(t)), f = t - i;
  return `rgb(${s[i].map((a, j) => Math.round(a + (s[i + 1][j] - a) * f))})`; }
// ---------- значения здания (как build_model.values_for) ----------
function valuesFor(i) {
  const names = CFG.exits.names, times = {};
  names.forEach((k, j) => { times[k] = B.t[j][i] < 0 ? null : B.t[j][i] / 10; });
  const ok = names.filter(k => times[k] != null).sort((a, b) => (times[a] - times[b]) || (names.indexOf(a) - names.indexOf(b)));
  return { best: ok.length ? ok[0] : null, backup: ok.length > 1 ? ok[1] : null,
    t_best: ok.length ? times[ok[0]] : null, t_backup: ok.length > 1 ? times[ok[1]] : null,
    has_path: B.lmh[i] === 1, lm_len: B.lml[i], lm_yard: B.lmy[i], lm_turns: B.lmt[i],
    res_n_100: B.rn1[i], res_n_200: B.rn2[i], res_share_200: B.rs2[i] / 1000, d_school: B.ds[i],
    city_center: B.cc[i] / 10, city_share_25: B.cs[i] / 1000, city_mean: B.cm[i] / 10, d_rail: B.dr[i],
    free: B.fr[i] / 1000, restr_d: B.rd[i], restr_reason: D.reasons[B.rr[i]], dead_end: B.de[i] === 1,
    oneway: B.ow[i], narrow: B.nw[i], closed_gap: B.cg[i], closed_reason: D.reasons[B.cr[i]],
    d_center: B.dc[i] / 100, mask: B.mask[i], no_path_exits: names.filter(k => times[k] == null), times };
}
// ---------- объяснения (как scoring.explain) ----------
const PLAIN = [["тип дороги track", "полевая дорога"], ["тип дороги living_street", "жилая зона"],
  ["тип дороги construction", "дорога строится"], ["тип дороги proposed", "дорога проектируется"],
  ["грунт", "грунтовая дорога"], ["motor_vehicle=no", "проезд закрыт"], ["access=no", "проезд закрыт"],
  ["vehicle=no", "проезд закрыт"], ["грузовым запрещено (OSM)", "грузовым запрещено"]];
function plainReason(r) { for (const [k, v] of PLAIN) if (r.startsWith(k)) return v; return r; }
const qn = n => n.startsWith("«") ? n : `«${n}»`;   // как scoring.qn
function groupText(g, v, positive) {   // как scoring.group_text
  if (g === "exit") {
    if (v.best == null) return positive ? null : "нет пути фуры ни к одному выезду";
    let t = `выезд ${qn(v.best)} — ${f0(v.t_best)} мин`;
    if (v.backup != null) t += `, запасной ${qn(v.backup)} — ${f0(v.t_backup)} мин`;
    if (positive) return v.t_best <= 20 ? "рядом " + t : null;
    return v.t_best > 15 ? "далеко до выездов: " + t : null;
  }
  if (g === "lastmile") {
    if (!v.has_path) return positive ? null : "нет пути фуры до магистрали";
    if (positive) { if (v.lm_len > 800 || v.lm_yard >= 200) return null;
      const t = `до магистрали ${r10(v.lm_len)} м по дорогам для фур`; return v.lm_yard < 50 ? t + ", без жилых дворов" : t; }
    if (v.lm_yard >= 100) return `подъезд идёт ${r10(v.lm_yard)} м по жилым улицам и дворам`;
    if (v.lm_len > 800) return `до магистрали далеко: ${r10(v.lm_len)} м`;
    return null;
  }
  if (g === "env") {
    if (positive) { if (v.res_n_200 > 10) return null;
      const t = `вокруг мало жилья: в 200 м жилых домов ${f0(v.res_n_200)}`; return v.d_school >= 500 ? t + ", школ и детсадов рядом нет" : t; }
    if (v.res_n_200 >= 10) { const t = `рядом жильё: в 200 м жилых домов ${f0(v.res_n_200)}`;
      return v.d_school < 300 ? t + `, школа или детсад в ${r10(v.d_school)} м` : t; }
    if (v.d_school < 300) return `школа или детсад в ${r10(v.d_school)} м`;
    return null;
  }
  if (g === "city") {
    if (positive) { if (v.city_share_25 < 0.35 && v.city_center > 20) return null;
      return `до центра города ${f0(v.city_center)} мин, ${f0(100 * v.city_share_25)}% городского спроса в 25 мин`; }
    return v.city_mean >= 30 ? `далеко от покупателей в городе: в среднем ${f0(v.city_mean)} мин до центров спроса` : null;
  }
  if (g === "infra") {
    if (positive) { if (v.d_rail < 1000) return `ж/д ветка в ${r10(v.d_rail)} м`;
      if (v.free >= 0.8) return `вокруг свободно: ${f0(100 * v.free)}% площади в 30 м не застроено`; return null; }
    if (v.free < 0.6) return `вокруг тесно: свободно только ${f0(100 * v.free)}% площади в 30 м`;
    if (v.d_rail >= 1500) return `ж/д далеко (${f1(v.d_rail / 1000)} км)`;
    return null;
  }
  return null;
}
function explain(i) {
  const v = valuesFor(i), c = {}; GROUPS.forEach(g => c[g] = B["c_" + g][i] / 10);
  const pos = GROUPS.filter(g => c[g] >= 1).sort((a, b) => (c[b] - c[a]) || (GROUPS.indexOf(a) - GROUPS.indexOf(b)));
  const neg = GROUPS.filter(g => c[g] <= -1).sort((a, b) => (c[a] - c[b]) || (GROUPS.indexOf(a) - GROUPS.indexOf(b)));
  const pros = pos.map(g => groupText(g, v, true)).filter(Boolean).slice(0, 3);
  const cons = neg.map(g => groupText(g, v, false)).filter(Boolean).slice(0, 3);
  const warn = [];
  if (!v.has_path) warn.push("нет пути фуры до магистрали по дорогам, открытым для грузовиков");
  else if (v.lm_yard >= 200) warn.push(`по пути к магистрали ${r10(v.lm_yard)} м жилых улиц и дворов`);
  if (v.res_n_100 >= 10 || v.res_share_200 >= 0.5) warn.push("внутри жилой застройки: шум и недовольство жителей");
  if (v.d_school < 300) warn.push(`школа или детсад в ${r10(v.d_school)} м`);
  if (v.restr_d < 1000) warn.push(`в ${r10(v.restr_d)} м ограничение для фур: ${plainReason(v.restr_reason)}`);
  if (v.dead_end) warn.push("здание на тупиковом проезде: фуре нужно место для разворота");
  if (v.oneway >= 2) warn.push(`на пути к магистрали односторонних участков: ${f0(v.oneway)}`);
  if (v.narrow >= 50) warn.push(`узкие проезды на пути: ${r10(v.narrow)} м`);
  if (v.closed_gap > 50 && v.closed_reason) warn.push(`ближайшая дорога закрыта для фур (${plainReason(v.closed_reason)}), объезд ${r10(v.closed_gap)} м`);
  if (v.d_center < 3) warn.push("близко к центру: там чаще действуют ограничения для грузовиков");
  if (v.no_path_exits.length) warn.push("нет пути фуры до: " + v.no_path_exits.join(", "));
  const rules = CFG.rules.filter(r => v.mask & BITS[r.id]).map(r => r.text);
  return { v, c, pros: pros.length ? pros : ["заметных преимуществ нет"], cons, warnings: warn, rules };
}
const osmUrl = i => B.id[i] < 0 ? `https://www.openstreetmap.org/relation/${-B.id[i]}` : `https://www.openstreetmap.org/way/${B.id[i]}`;
function addrOf(i) { return B.addr[i] || (D.streets[B.street[i]] ? "рядом с " + D.streets[B.street[i]] : "адрес не найден"); }
// ---------- пространственный индекс зданий ----------
const GS = 0.004, bGrid = new Map();
for (let i = 0; i < NB; i++) { const k = Math.floor(B.lat[i] / GS) + "," + Math.floor(B.lon[i] / GS);
  if (!bGrid.has(k)) bGrid.set(k, []); bGrid.get(k).push(i); }
function near(lat, lon, radius) {
  const r = Math.ceil(radius / (GS * KX)) + 1, gy = Math.floor(lat / GS), gx = Math.floor(lon / GS), out = [];
  for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++)
    for (const i of bGrid.get((gy + dy) + "," + (gx + dx)) || []) if (distM(B.lat[i], B.lon[i], lat, lon) <= radius) out.push(i);
  return out;
}
const polyCache = new Map();
const poly = i => { if (!polyCache.has(i)) polyCache.set(i, decode(B.poly[i], 1e6)); return polyCache.get(i); };
function inside(lat, lon, pts) { let c = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [yi, xi] = pts[i], [yj, xj] = pts[j];
    if ((yi > lat) !== (yj > lat) && lon < (xj - xi) * (lat - yi) / (yj - yi) + xi) c = !c; }
  return c; }
function buildingAt(lat, lon) {
  const cand = near(lat, lon, 300).sort((a, b) => distM(B.lat[a], B.lon[a], lat, lon) - distM(B.lat[b], B.lon[b], lat, lon));
  for (const i of cand) if (inside(lat, lon, poly(i))) return i;
  return -1;
}
function bestNear(lat, lon, radius, profile, exclude, n) {
  return near(lat, lon, radius).filter(i => i !== exclude)
    .sort((a, b) => (profileScore(b, profile) - profileScore(a, profile)) || (a - b)).slice(0, n);
}
"""

# ====================================================================== своя карта на canvas (без библиотек)
ENGINE_JS = r"""
// Мини-движок карты: проекция Web Mercator, плитки OpenStreetMap, перетаскивание, колёсико, клик, подсказки.
class MiniMap {
  constructor(el, opt) {
    this.el = el; el.style.position = "relative"; el.style.overflow = "hidden"; el.style.touchAction = "none";
    this.cv = document.createElement("canvas"); this.cv.style.cssText = "position:absolute;inset:0;width:100%;height:100%;cursor:grab";
    el.appendChild(this.cv); this.ctx = this.cv.getContext("2d");
    this.tip = document.createElement("div"); this.tip.className = "mm-tip"; el.appendChild(this.tip);
    const ui = document.createElement("div"); ui.className = "mm-zoom";
    ui.innerHTML = `<button aria-label="Приблизить">+</button><button aria-label="Отдалить">−</button>`; el.appendChild(ui);
    ui.children[0].onclick = () => this.zoomAt(this.W / 2, this.H / 2, 1);
    ui.children[1].onclick = () => this.zoomAt(this.W / 2, this.H / 2, -1);
    this.attr = document.createElement("div"); this.attr.className = "mm-attr"; el.appendChild(this.attr);
    this.attr.innerHTML = opt.attribution || "";
    this.lat = opt.center[0]; this.lon = opt.center[1]; this.z = opt.zoom; this.minZ = 9; this.maxZ = 19;
    this.tilesOn = opt.tiles !== false; this.cache = new Map(); this.tileOk = 0; this.tileFail = 0;
    this.h = {}; this.drawFn = () => {};
    this.resize(); new ResizeObserver(() => this.resize()).observe(el);
    let down = null, moved = false;
    this.cv.addEventListener("pointerdown", e => { down = { x: e.clientX, y: e.clientY, lat: this.lat, lon: this.lon }; moved = false;
      this.cv.setPointerCapture(e.pointerId); this.cv.style.cursor = "grabbing"; });
    this.cv.addEventListener("pointermove", e => {
      const r = this.cv.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
      if (down) { const dx = e.clientX - down.x, dy = e.clientY - down.y; if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
        if (moved) { const s = 256 * 2 ** this.z, x0 = MiniMap.wx(down.lon, s) - dx, y0 = MiniMap.wy(down.lat, s) - dy;
          this.lon = MiniMap.lonOf(x0, s); this.lat = MiniMap.latOf(y0, s); this.request(true); this.hideTip(); } }
      else if (this.h.hover) { this._hp = [px, py]; if (!this._hq) { this._hq = true; requestAnimationFrame(() => { this._hq = false;
        const [x, y] = this._hp, ll = this.toLatLng(x, y); this.h.hover(ll[0], ll[1], x, y); }); } } });
    this.cv.addEventListener("pointerup", e => { this.cv.style.cursor = "grab";
      if (down && !moved && this.h.click) { const r = this.cv.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
        const ll = this.toLatLng(px, py); this.h.click(ll[0], ll[1], px, py); }
      if (down && moved) this.fire("moveend"); down = null; });
    this.cv.addEventListener("pointerleave", () => this.hideTip());
    this.cv.addEventListener("wheel", e => { e.preventDefault(); const r = this.cv.getBoundingClientRect();
      this.zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 0.5 : -0.5); }, { passive: false });
    this.cv.addEventListener("dblclick", e => { const r = this.cv.getBoundingClientRect(); this.zoomAt(e.clientX - r.left, e.clientY - r.top, 1); });
  }
  static wx(lon, s) { return (lon + 180) / 360 * s; }
  static wy(lat, s) { const v = Math.sin(lat * Math.PI / 180); return (0.5 - Math.log((1 + v) / (1 - v)) / (4 * Math.PI)) * s; }
  static lonOf(x, s) { return x / s * 360 - 180; }
  static latOf(y, s) { const n = Math.PI - 2 * Math.PI * y / s; return 180 / Math.PI * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n))); }
  on(ev, fn) { this.h[ev] = fn; return this; }
  fire(ev) { if (this.h[ev]) this.h[ev](); }
  resize() { const r = this.el.getBoundingClientRect(), d = window.devicePixelRatio || 1;
    this.W = Math.max(1, r.width); this.H = Math.max(1, r.height); this.cv.width = this.W * d; this.cv.height = this.H * d;
    this.ctx.setTransform(d, 0, 0, d, 0, 0); this.request(); }
  get scale() { return 256 * 2 ** this.z; }
  pt(lat, lon) { const s = this.scale; return [MiniMap.wx(lon, s) - MiniMap.wx(this.lon, s) + this.W / 2, MiniMap.wy(lat, s) - MiniMap.wy(this.lat, s) + this.H / 2]; }
  toLatLng(px, py) { const s = this.scale; return [MiniMap.latOf(MiniMap.wy(this.lat, s) + py - this.H / 2, s), MiniMap.lonOf(MiniMap.wx(this.lon, s) + px - this.W / 2, s)]; }
  bounds() { const [n, w] = this.toLatLng(0, 0), [s, e] = this.toLatLng(this.W, this.H); return { s, w, n, e }; }
  getZoom() { return this.z; }
  setView(ll, z) { this.lat = ll[0]; this.lon = ll[1]; if (z != null) this.z = Math.max(this.minZ, Math.min(this.maxZ, z)); this.request(); this.fire("moveend"); }
  fitBounds(s, w, n, e, maxZ, pad = 30) {
    let z = this.maxZ; for (; z > this.minZ; z -= 0.5) { const S = 256 * 2 ** z;
      if ((MiniMap.wx(e, S) - MiniMap.wx(w, S)) <= this.W - 2 * pad && (MiniMap.wy(s, S) - MiniMap.wy(n, S)) <= this.H - 2 * pad) break; }
    const S = 256 * 2 ** z; this.setView([MiniMap.latOf((MiniMap.wy(s, S) + MiniMap.wy(n, S)) / 2, S), (w + e) / 2], Math.min(z, maxZ || this.maxZ)); }
  zoomAt(px, py, dz) { const nz = Math.max(this.minZ, Math.min(this.maxZ, Math.round((this.z + dz) * 2) / 2)); if (nz === this.z) return;
    const ll = this.toLatLng(px, py); this.z = nz; const s = this.scale;
    this.lon = MiniMap.lonOf(MiniMap.wx(ll[1], s) - px + this.W / 2, s); this.lat = MiniMap.latOf(MiniMap.wy(ll[0], s) - py + this.H / 2, s);
    this.hideTip(); this.request(); clearTimeout(this._mt); this._mt = setTimeout(() => this.fire("moveend"), 150); }
  request(fast) { if (this._raf) return; this._raf = requestAnimationFrame(() => { this._raf = 0; this.draw(fast); }); }
  tile(z, x, y) { const k = z + "/" + x + "/" + y; let t = this.cache.get(k);
    if (!t) { t = new Image(); t.crossOrigin = "anonymous"; t.ok = false;
      t.onload = () => { t.ok = true; this.tileOk++; this.request(); };
      t.onerror = () => { this.tileFail++; if (this.h.tileerror) this.h.tileerror(); };
      t.src = `https://tile.openstreetmap.org/${z}/${x}/${y}.png`; this.cache.set(k, t);
      if (this.cache.size > 600) this.cache.delete(this.cache.keys().next().value); }
    return t; }
  draw(fast) {
    const c = this.ctx; c.fillStyle = "#ece9e1"; c.fillRect(0, 0, this.W, this.H);
    this.tilesShown = false;
    if (this.tilesOn) {
      const tz = Math.min(19, Math.round(this.z)), k = 2 ** (this.z - tz), S = 256 * 2 ** tz, n = 2 ** tz;
      const cx = MiniMap.wx(this.lon, S), cy = MiniMap.wy(this.lat, S), w2 = this.W / 2 / k, h2 = this.H / 2 / k;
      for (let ty = Math.floor((cy - h2) / 256); ty <= Math.floor((cy + h2) / 256); ty++)
        for (let tx = Math.floor((cx - w2) / 256); tx <= Math.floor((cx + w2) / 256); tx++) {
          if (ty < 0 || ty >= n) continue; const t = this.tile(tz, ((tx % n) + n) % n, ty);
          const sx = (tx * 256 - cx) * k + this.W / 2, sy = (ty * 256 - cy) * k + this.H / 2;
          if (t.ok) { c.drawImage(t, sx, sy, 256 * k + 0.5, 256 * k + 0.5); this.tilesShown = true; } }
    }
    this.drawFn(c, fast);
  }
  showTip(html, px, py) { this.tip.innerHTML = html; this.tip.style.display = "block";
    this.tip.style.left = Math.min(px + 14, this.W - 260) + "px"; this.tip.style.top = (py + 14) + "px"; }
  hideTip() { this.tip.style.display = "none"; }
  // рисование
  path(pts) { const c = this.ctx; c.beginPath(); pts.forEach(([la, lo], j) => { const [x, y] = this.pt(la, lo); j ? c.lineTo(x, y) : c.moveTo(x, y); }); }
  circle(lat, lon, r, fill, stroke, lw) { const c = this.ctx, [x, y] = this.pt(lat, lon); c.beginPath(); c.arc(x, y, r, 0, 2 * Math.PI);
    if (fill) { c.fillStyle = fill; c.fill(); } if (stroke) { c.strokeStyle = stroke; c.lineWidth = lw || 1; c.stroke(); } return [x, y]; }
}
"""

MAP_CSS = """
.mm-tip { position: absolute; z-index: 5; display: none; pointer-events: none; background: #fff; border: 1px solid var(--line); border-radius: 6px; padding: 4px 8px; font-size: 12px; box-shadow: 0 4px 12px rgba(0,0,0,.12); max-width: 260px; }
.mm-zoom { position: absolute; z-index: 5; left: 10px; top: 10px; display: flex; flex-direction: column; box-shadow: 0 2px 6px rgba(0,0,0,.2); border-radius: 6px; overflow: hidden; }
.mm-zoom button { width: 32px; height: 32px; border: 0; border-bottom: 1px solid #ddd; background: #fff; font: 700 18px var(--font); cursor: pointer; color: #333; }
.mm-zoom button:hover { background: #f2f2f2; }
.mm-attr { position: absolute; z-index: 5; right: 0; bottom: 0; background: rgba(255,255,255,.8); font-size: 11px; padding: 1px 6px; color: #333; }
"""

HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Склады Саратова</title>
<style>
:root { --bg:#f4f3ef; --panel:#fff; --ink:#1f2429; --muted:#5f6771; --line:#dedbd2; --hot:#b42318; --zone:#b7791f; --accent:#1d4ed8;
  --font:"Segoe UI", system-ui, -apple-system, Roboto, sans-serif; }
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; font: 14px/1.45 var(--font); color: var(--ink); background: var(--bg); }
#app { display: grid; grid-template-columns: 410px 1fr; height: 100%; }
@media (max-width: 820px) { #app { grid-template-columns: 1fr; grid-template-rows: 55% 45%; } }
aside { overflow-y: auto; background: var(--panel); border-right: 1px solid var(--line); padding: 14px 16px 28px; }
#map { height: 100%; background: #ece9e1; }
h1 { font-size: 19px; margin: 0 0 4px; line-height: 1.25; }
.lead { color: var(--muted); margin: 0 0 10px; font-size: 13px; }
h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted); margin: 18px 0 8px; }
h3 { font-size: 13px; margin: 12px 0 4px; }
.hint { font-size: 13px; color: var(--muted); }
#search-wrap { position: relative; }
#search { width: 100%; padding: 8px 10px; border: 1px solid var(--line); border-radius: 8px; font: 14px var(--font); }
#sugg { position: absolute; z-index: 1000; left: 0; right: 0; background: #fff; border: 1px solid var(--line); border-radius: 8px; margin-top: 2px; display: none; max-height: 300px; overflow-y: auto; box-shadow: 0 6px 18px rgba(0,0,0,.08); }
#sugg div { padding: 6px 10px; cursor: pointer; font-size: 13px; }
#sugg div:hover, #sugg div.act { background: var(--bg); }
.seg { display: flex; gap: 4px; margin: 10px 0 4px; flex-wrap: wrap; }
.seg button { flex: 1; padding: 6px 4px; border: 1px solid var(--line); background: #fff; border-radius: 6px; cursor: pointer; font: 600 12px var(--font); color: var(--ink); }
.seg button.on { background: var(--ink); color: #fff; border-color: var(--ink); }
#card { border: 1px solid var(--line); border-radius: 10px; padding: 12px 14px; background: #fcfbf8; margin-top: 10px; }
.badge { display: inline-block; color: #fff; font-weight: 700; padding: 2px 10px; border-radius: 12px; font-size: 13px; }
.total { font-size: 22px; font-weight: 800; margin: 6px 0 2px; }
.meta { font-size: 13px; color: var(--muted); } .meta b { color: var(--ink); font-weight: 600; }
.bar { display: grid; grid-template-columns: 170px 1fr 34px; align-items: center; gap: 8px; font-size: 13px; margin: 3px 0; }
.bar .track { display: block; height: 8px; background: #e8e5dc; border-radius: 4px; overflow: hidden; }
.bar .fill { display: block; height: 100%; border-radius: 4px; }
.bar .v { text-align: right; font-variant-numeric: tabular-nums; }
.cbar { display: grid; grid-template-columns: 170px 1fr 40px; align-items: center; gap: 8px; font-size: 13px; margin: 2px 0; }
.cbar .axis { position: relative; height: 8px; background: #efece5; border-radius: 4px; }
.cbar .axis span { position: absolute; top: 0; height: 100%; border-radius: 4px; }
.cbar .axis:after { content: ""; position: absolute; left: 50%; top: -2px; bottom: -2px; width: 1px; background: #9a978e; }
.cbar .v { text-align: right; font-variant-numeric: tabular-nums; }
ul.list { margin: 4px 0; padding-left: 18px; } ul.list li { margin: 2px 0; }
ul.warn li::marker { color: var(--hot); } ul.cons li::marker { color: #b7791f; }
.rule { background: #fdecea; border: 1px solid #f3c2bc; border-radius: 6px; padding: 6px 8px; font-size: 13px; margin: 8px 0; }
.times { display: grid; grid-template-columns: 1fr auto; gap: 1px 10px; font-size: 13px; }
.times span:nth-child(even) { text-align: right; font-variant-numeric: tabular-nums; }
button.small { padding: 5px 10px; border: 1px solid var(--line); background: var(--bg); border-radius: 6px; cursor: pointer; font: 600 12px var(--font); color: var(--ink); margin: 4px 4px 0 0; }
button.small:hover { background: #ebe8df; }
details { margin-top: 10px; font-size: 13px; } details summary { cursor: pointer; font-weight: 600; }
label.layer { display: flex; gap: 8px; align-items: center; padding: 3px 0; cursor: pointer; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
td, th { padding: 5px 4px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
th { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; font-weight: 600; }
td.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.zone-row { cursor: pointer; } .zone-row:hover { background: var(--bg); }
.znum { display: inline-block; font-size: 11px; font-weight: 700; padding: 1px 6px; border-radius: 9px; background: #fff3d6; color: #7a4f00; }
.legend-bar { height: 10px; border-radius: 3px; background: linear-gradient(90deg, #b42318, #e8a317, #f7f0aa, #41ab5d, #006837); margin: 4px 0 2px; }
.legend-scale { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); }
.note { font-size: 12px; color: var(--muted); border-top: 1px solid var(--line); margin-top: 18px; padding-top: 10px; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; vertical-align: -1px; }
a { color: var(--accent); }
button:focus-visible, input:focus-visible, tr:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
/*MAPCSS*/
</style>
</head>
<body>
<div id="app">
<aside>
  <h1>Где ставить склад в Саратове</h1>
  <p class="lead">Введите адрес объявления или нажмите на здание (здания с оценкой видны при приближении). Модель оценит, насколько место подходит под склад, и объяснит почему.</p>
  <div id="search-wrap"><input id="search" type="search" placeholder="Адрес: например, Вольский тракт 1" aria-label="Поиск по адресу" autocomplete="off"><div id="sugg"></div></div>
  <div class="seg" id="profiles" role="group" aria-label="Профиль склада"></div>
  <div id="card"><p class="hint">Карточка здания появится здесь. Или выберите зону из списка «Лучшие зоны».</p></div>

  <h2>Лучшие зоны (профиль «Универсальный»)</h2>
  <table id="zones"><thead><tr><th>#</th><th>Где</th><th class="num">Балл</th></tr></thead><tbody></tbody></table>

  <h2>Слои</h2>
  <div class="legend-bar"></div><div class="legend-scale"><span>0 — плохо</span><span>цвет здания = итог профиля</span><span>100 — отлично</span></div>
  <label class="layer"><input type="checkbox" id="l-bld" checked> Здания с оценкой (с приближения 15)</label>
  <label class="layer"><input type="checkbox" id="l-top" checked> Лучшие здания точками (при отдалении)</label>
  <label class="layer"><input type="checkbox" id="l-zones" checked> Номера лучших зон</label>
  <label class="layer"><input type="checkbox" id="l-osm" checked> Обычная карта OpenStreetMap (нужен интернет)</label>
  <div id="status" class="hint"></div>
  <p class="hint"><a href="label.html" id="label-link">Разметка экспертами</a> — оценить 150 зданий «хорошо / средне / плохо», чтобы проверить и дообучить модель.</p>
  <p class="note" id="model-note"></p>
</aside>
<div id="map" aria-label="Карта"></div>
</div>
<script src="map_data.js"></script>
<script>
/*COMMON*/
/*ENGINE*/
// ---------- граф (маршруты фуры) ----------
const pieces = D.pieces.map(f => decode(f)), PC = D.pc, EL = [];
PC.d.forEach((d, pi) => { if (d === 0 || d === 1) EL.push([pi, 0]); if (d === 0 || d === 2) EL.push([pi, 1]); });
const E = EL.length;
const eFrom = new Int32Array(E), eTo = new Int32Array(E), ePiece = new Int32Array(E), eWay = new Int32Array(E);
const eTime = new Float64Array(E), eRev = new Uint8Array(E), hIn = new Float64Array(E), hOut = new Float64Array(E);
const outE = new Map(), inE = new Map(), pieceEdges = new Map();
const head = (a, b) => Math.atan2((b[0] - a[0]) * KY, (b[1] - a[1]) * KX) * 180 / Math.PI;   // курс в градусах, как в Python
EL.forEach(([pi, rev], i) => { const c = rev ? pieces[pi].slice().reverse() : pieces[pi];
  eFrom[i] = rev ? PC.v[pi] : PC.u[pi]; eTo[i] = rev ? PC.u[pi] : PC.v[pi]; eTime[i] = PC.t[pi] / 1000; ePiece[i] = pi; eRev[i] = rev; eWay[i] = PC.w[pi];
  hOut[i] = head(c[0], c[1]); hIn[i] = head(c[c.length - 2], c[c.length - 1]);
  if (!outE.has(eFrom[i])) outE.set(eFrom[i], []); outE.get(eFrom[i]).push(i);
  if (!inE.has(eTo[i])) inE.set(eTo[i], []); inE.get(eTo[i]).push(i);
  if (!pieceEdges.has(pi)) pieceEdges.set(pi, []); pieceEdges.get(pi).push(i); });
const turnNo = new Set(D.turnNo.map(t => t.join(","))), turnOnly = new Map(D.turnOnly.map(t => [t[0] + "," + t[1], t[2]])), TP = D.turnPenalty;
function allowed(a, b) { const n = eTo[a]; if (turnNo.has(eWay[a] + "," + n + "," + eWay[b])) return false;
  const only = turnOnly.get(eWay[a] + "," + n); return only === undefined || only === eWay[b]; }
function turn(a, b) { if (a !== b && ePiece[a] === ePiece[b]) return TP.uturn;
  const ang = (((hOut[b] - hIn[a] + 180) % 360) + 360) % 360 - 180;
  if (Math.abs(ang) > 135) return TP.uturn; if (ang > 60) return TP.left; if (ang < -60) return TP.right; return 0; }
class Heap { constructor() { this.k = []; this.v = []; }
  push(key, val) { const k = this.k, v = this.v; let i = k.length; k.push(key); v.push(val);
    while (i > 0) { const p = (i - 1) >> 1; if (k[p] <= k[i]) break; [k[p], k[i]] = [k[i], k[p]]; [v[p], v[i]] = [v[i], v[p]]; i = p; } }
  pop() { const k = this.k, v = this.v, top = [k[0], v[0]], lk = k.pop(), lv = v.pop();
    if (k.length) { k[0] = lk; v[0] = lv; let i = 0;
      for (;;) { const l = 2 * i + 1, r = l + 1; let m = i; if (l < k.length && k[l] < k[m]) m = l; if (r < k.length && k[r] < k[m]) m = r;
        if (m === i) break; [k[m], k[i]] = [k[i], k[m]]; [v[m], v[i]] = [v[i], v[m]]; i = m; } }
    return top; }
  get size() { return this.k.length; } }
const exitSets = D.exits.map(x => new Set(x.nodes));
function chain(e, ptr) { const out = []; let n = 0; while (e !== -1 && n++ < 20000) { out.push(e); e = ptr[e]; } return out; }
function routes(piece, outward) {
  const dist = new Float64Array(E).fill(Infinity), ptr = new Int32Array(E).fill(-1), h = new Heap();
  for (const e of pieceEdges.get(piece) || []) { dist[e] = eTime[e]; h.push(dist[e], e); }
  const found = new Array(D.exits.length).fill(null); let left = found.length;
  while (h.size && left) { const [d, e] = h.pop(); if (d > dist[e]) continue;
    exitSets.forEach((s, k) => { if (!found[k] && s.has(outward ? eTo[e] : eFrom[e])) { found[k] = { time: d, edge: e }; left--; } });
    if (outward) { for (const s of outE.get(eTo[e]) || []) { if (!allowed(e, s)) continue; const nd = d + turn(e, s) + eTime[s]; if (nd < dist[s]) { dist[s] = nd; ptr[s] = e; h.push(nd, s); } } }
    else { for (const p of inE.get(eFrom[e]) || []) { if (!allowed(p, e)) continue; const nd = d + eTime[p] + turn(p, e); if (nd < dist[p]) { dist[p] = nd; ptr[p] = e; h.push(nd, p); } } } }
  return found.map(f => f && { time: f.time, path: outward ? chain(f.edge, ptr).reverse() : chain(f.edge, ptr) });
}
function pathLatLngs(path) { const ll = []; for (const e of path) { let c = pieces[ePiece[e]]; if (eRev[e]) c = c.slice().reverse(); ll.push(...c); } return ll; }
const EXIT_COLORS = ["#1d4ed8", "#c026d3", "#0f766e", "#b45309", "#4d7c0f", "#be123c"];
// рамки участков дорог (для отрисовки только видимых)
const pBox = pieces.map(p => { let s = 90, n = -90, w = 180, e = -180; for (const [la, lo] of p) { s = Math.min(s, la); n = Math.max(n, la); w = Math.min(w, lo); e = Math.max(e, lo); } return [s, w, n, e]; });

// ---------- состояние ----------
let profile = CFG.default_profile;
try { const p = localStorage.getItem("wh-profile"); if (p && CFG.profiles[p]) profile = p; } catch (e) {}
let current = -1, hover = -1, routesShown = null, zoneHi = null, pin = null;
const $ = id => document.getElementById(id);
const M = new MiniMap($("map"), { center: [51.56, 46.0], zoom: 11, tiles: location.protocol !== "file:",
  attribution: "Подложка, дороги и здания: © участники OpenStreetMap" });
if (location.protocol === "file:") $("l-osm").checked = false;
let scoreCache = null;
function scores() { if (!scoreCache) { scoreCache = new Float64Array(NB); for (let i = 0; i < NB; i++) scoreCache[i] = profileScore(i, profile); } return scoreCache; }
let topIdx = null;
function topList() { if (!topIdx) { const s = scores(); topIdx = Array.from({ length: NB }, (_, i) => i).filter(i => s[i] >= 75).sort((a, b) => s[b] - s[a]).slice(0, 800); } return topIdx; }
function fillOf(i) { if (B.mask[i] & (BITS.residential_type | BITS.residential_quarter | BITS.no_access)) return "#a3a3a3"; return color(scores()[i]); }

// ---------- отрисовка ----------
M.drawFn = (c, fast) => {
  const z = M.getZoom(), b = M.bounds();
  // свои дороги — если подложки нет или она не загрузилась
  if (!M.tilesShown) {
    for (let pi = 0; pi < pieces.length; pi++) { const main = D.pieceMain[pi]; if (!main && z < 13) continue;
      const bx = pBox[pi]; if (bx[2] < b.s || bx[0] > b.n || bx[3] < b.w || bx[1] > b.e) continue;
      M.path(pieces[pi]); c.strokeStyle = main ? "#8a8d92" : "#c3c0b6"; c.lineWidth = main ? 2 : 0.8; c.stroke(); }
  }
  // здания (с приближения 15)
  if (z >= 15 && $("l-bld").checked) {
    c.globalAlpha = M.tilesShown ? 0.72 : 0.9; c.lineWidth = 0.6; c.strokeStyle = "#4b4f55";
    for (let gy = Math.floor(b.s / GS); gy <= Math.floor(b.n / GS); gy++)
      for (let gx = Math.floor(b.w / GS); gx <= Math.floor(b.e / GS); gx++)
        for (const i of bGrid.get(gy + "," + gx) || []) { M.path(poly(i)); c.closePath(); c.fillStyle = fillOf(i); c.fill(); if (!fast) c.stroke(); }
    c.globalAlpha = 1;
  } else if (z < 15 && $("l-top").checked) {
    const s = scores(); for (const i of topList()) M.circle(B.lat[i], B.lon[i], z < 12 ? 2.5 : 3.5, color(s[i]), "rgba(0,0,0,.35)", 0.5);
  }
  // маршруты
  if (routesShown) routesShown.forEach((x, k) => { if (!x) return; M.path(pathLatLngs(x.path)); c.strokeStyle = "#fff"; c.lineWidth = 7; c.stroke(); c.strokeStyle = EXIT_COLORS[k]; c.lineWidth = 4.5; c.stroke(); });
  // подсветка зоны
  if (zoneHi) { c.strokeStyle = "#111"; c.lineWidth = 2; for (const r of zoneHi) { const [x1, y1] = M.pt(r[1][0], r[0][1]), [x2, y2] = M.pt(r[0][0], r[1][1]); c.strokeRect(x1, y1, x2 - x1, y2 - y1); } }
  // наведённое и выбранное здание
  if (hover >= 0 && z >= 15) { M.path(poly(hover)); c.closePath(); c.strokeStyle = "#111"; c.lineWidth = 2.5; c.stroke(); }
  if (current >= 0) { M.path(poly(current)); c.closePath(); c.strokeStyle = "#111"; c.lineWidth = 3.5; c.stroke();
    if (z < 15) M.circle(B.lat[current], B.lon[current], 7, "#fff", "#111", 3); }
  if (pin) M.circle(pin[0], pin[1], 7, "#fff", "#111", 2.5);
  // выезды
  D.exits.forEach((x, k) => { if (x.lonlat) M.circle(x.lonlat[1], x.lonlat[0], 8, EXIT_COLORS[k], "#fff", 2); });
  // номера зон
  if ($("l-zones").checked) zoneMarks().forEach(([k, i]) => { const [x, y] = M.circle(B.lat[i], B.lon[i], 10, "#b7791f", "#fff", 2);
    c.fillStyle = "#fff"; c.font = "700 11px Segoe UI, sans-serif"; c.textAlign = "center"; c.textBaseline = "middle"; c.fillText(String(k + 1), x, y + 0.5); });
};
const zoneMarks = () => D.zones.slice(0, CFG.zones.top_n).map((z, k) => [k, z.best]);
function hitMarker(px, py) {
  if ($("l-zones").checked) for (const [k, i] of zoneMarks()) { const [x, y] = M.pt(B.lat[i], B.lon[i]); if (Math.hypot(x - px, y - py) <= 11) return { zone: k }; }
  for (let k = 0; k < D.exits.length; k++) { const x = D.exits[k]; if (!x.lonlat) continue; const [sx, sy] = M.pt(x.lonlat[1], x.lonlat[0]);
    if (Math.hypot(sx - px, sy - py) <= 9) return { exit: k }; }
  return null;
}
M.on("click", (lat, lon, px, py) => {
  const m = hitMarker(px, py); if (m && m.zone != null) return showZone(m.zone);
  const i = buildingAt(lat, lon); i >= 0 ? showBuilding(i, false) : showNoBuilding(lat, lon);
});
M.on("hover", (lat, lon, px, py) => {
  const m = hitMarker(px, py);
  if (m) { M.cv.style.cursor = "pointer"; if (hover !== -1) { hover = -1; M.request(); }
    return M.showTip(m.zone != null ? `<b>Зона ${m.zone + 1}</b> · ${f0(D.zones[m.zone].score)} — нажмите, чтобы открыть` : `Выезд: <b>${esc(D.exits[m.exit].name)}</b>`, px, py); }
  M.cv.style.cursor = "grab";
  const i = M.getZoom() >= 15 && $("l-bld").checked ? buildingAt(lat, lon) : -1;
  if (i !== hover) { hover = i; M.request(); }
  if (i >= 0) M.showTip(`${esc(addrOf(i))} · <b>${f0(scores()[i])}</b>`, px, py); else M.hideTip();
});
M.on("tileerror", () => { if (M.tileOk) return; $("status").textContent = location.protocol === "file:"
  ? "Обычная карта OSM не грузится в файле, открытом с диска: рисуем свои дороги. Для подложки откройте «Открыть карту складов.cmd»."
  : "Обычная карта OSM не загрузилась: проверьте интернет. Рисуем свои дороги."; });

// ---------- профиль ----------
const segEl = $("profiles");
Object.entries(CFG.profiles).forEach(([key, p]) => { const b = document.createElement("button"); b.textContent = p.name; b.dataset.p = key;
  b.onclick = () => setProfile(key); segEl.appendChild(b); });
function setProfile(p) { profile = p; scoreCache = null; topIdx = null; try { localStorage.setItem("wh-profile", p); } catch (e) {}
  segEl.querySelectorAll("button").forEach(b => b.classList.toggle("on", b.dataset.p === p));
  M.request(); if (current >= 0) showBuilding(current, false); }

// ---------- карточка здания ----------
const card = $("card");
function bar(label, v, hint) { return `<div class="bar" title="${esc(hint || "")}"><span>${label}</span><span class="track"><span class="fill" style="width:${clip(v)}%;background:${color(v)}"></span></span><span class="v">${f0(v)}</span></div>`; }
function cbar(label, c) { const w = Math.min(50, Math.abs(c) / 2), left = c >= 0 ? 50 : 50 - w;
  return `<div class="cbar"><span>${label}</span><span class="axis"><span style="left:${left}%;width:${w}%;background:${c >= 0 ? "#41ab5d" : "#d9822b"}"></span></span><span class="v">${c > 0 ? "+" : ""}${f0(c)}</span></div>`; }
const UNKNOWN = `<details><summary>Как это считается и чего мы не знаем</summary>
  <p><b>Итог</b> = ${CFG.alpha} × балл модели + ${(1 - CFG.alpha).toFixed(1)} × формула профиля, затем правила безопасности.</p>
  <ul class="list">
  <li><b>Балл модели</b>: «лучше, чем X% зданий города». Модель (${esc(D.model.name)}) обучена отличать места, где склады и производства стоят сейчас, от остальных; проверена на районах, которых не видела (ROC-AUC ${D.model.auc}, у формулы ${D.model.formulaAuc}).</li>
  <li><b>Формула профиля</b>: выезд, доставка по городу, последняя миля, само здание, ж/д и соседние склады; веса — в warehouse_config.json.</li>
  <li><b>Вклад групп</b>: насколько изменился бы балл модели, если бы эта группа признаков была «как у среднего здания города».</li>
  <li><b>Правила</b>: ≤ 20 без проезда, ≤ 40 через жилые дворы, ≤ 30 жилой дом, ≤ 40 здание без типа в жилом квартале, ≤ 50 меньше 100 м².</li></ul>
  <p><b>Чего мы не знаем:</b></p><ul class="list">
  <li>пробки — статическая модель загруженности, а не реальные пробки по часам;</li>
  <li>потоки фур модельные; доли фур по выездам (по 0.25) — допущение;</li>
  <li>метка модели — существующие склады OSM, а не экспертная оценка «хорошо/плохо»;</li>
  <li>спрос по городу — кластеры жилья и магазинов OSM, данных о населении нет;</li>
  <li>нет цен, аренды, свободных участков, мощностей, санитарных зон и объявлений;</li>
  <li>ограничения для фур — из OSM и нашего ручного списка мостов, список неполный.</li></ul></details>`;
function timesHtml(v) {
  return `<div class="times">${CFG.exits.names.map((k, j) => `<span><span class="dot" style="background:${EXIT_COLORS[j]}"></span>${esc(k)}</span><span>${v.times[k] == null ? "нет пути" : f0(v.times[k]) + " мин"}</span>`).join("")}
  <span>До центра города</span><span>${f0(v.city_center)} мин</span><span>Среднее до центров спроса</span><span>${f0(v.city_mean)} мин</span></div>`;
}
function showBuilding(i, move) {
  current = i; routesShown = null; zoneHi = null; pin = null;
  const total = profileScore(i, profile), bd = badgeOf(total), ex = explain(i), v = ex.v;
  if (move) M.setView([B.lat[i], B.lon[i]], Math.max(M.getZoom(), 16)); else M.request();
  const alt = bestNear(B.lat[i], B.lon[i], CFG.alternative_radius_km * 1000, profile, i, 1)[0];
  const altT = alt != null ? profileScore(alt, profile) : -1;
  const altHtml = alt != null && altT > total + 3 ? `<h3>Лучше рядом (до ${CFG.alternative_radius_km} км)</h3>
     <p>${esc(addrOf(alt))} — <b>${f0(altT)}</b> (на ${f0(altT - total)} лучше) <button class="small" id="alt-go">Показать</button></p>` : "";
  const name = B.name[i] ? esc(B.name[i]) + " — " : "";
  card.innerHTML = `<span class="badge" style="background:${bd.color}">${bd.label}</span> <span class="meta">профиль «${esc(CFG.profiles[profile].name)}»</span>
    <div class="total">${f0(total)} / 100</div>
    <div class="meta">Адрес: <b>${esc(addrOf(i))}</b><br>Здание: <b>${name}${esc(D.types[B.type[i]])}</b> · площадь <b>${B.area[i].toLocaleString("ru")} м²</b><br>
    Модель: место лучше, чем у <b>${f0(B.ml[i] / 10)}%</b> зданий города</div>
    ${ex.rules.length ? `<div class="rule"><b>Сработало правило:</b> ${ex.rules.map(esc).join("; ")}</div>` : ""}
    <h3>Время фуры (среднее туда и обратно)</h3>${timesHtml(v)}
    <h3>Из чего сложился итог</h3>
    ${bar("Балл модели", B.ml[i] / 10, "лучше, чем такой % зданий города")}
    ${PARTS.map(k => bar(D.partRu[k], B["s_" + k][i] / 10, "")).join("")}
    <h3>Почему подходит</h3><ul class="list">${ex.pros.map(t => `<li>${esc(t)}</li>`).join("")}</ul>
    ${ex.cons.length ? `<h3>Что мешает</h3><ul class="list cons">${ex.cons.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    ${ex.warnings.length ? `<h3>Предупреждения</h3><ul class="list warn">${ex.warnings.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    <details><summary>Вклад групп признаков в балл модели</summary>${GROUPS.map(g => cbar(D.featureGroupsRu[g], ex.c[g])).join("")}</details>
    ${altHtml}
    <h3>Маршруты фуры</h3>
    <button class="small" id="ro">склад → выезды</button><button class="small" id="ri">выезды → склад</button><div id="rt" class="hint"></div>
    ${UNKNOWN}<p class="hint">OSM: <a href="${osmUrl(i)}" target="_blank" rel="noopener">${B.id[i] < 0 ? "relation " + -B.id[i] : "way " + B.id[i]}</a></p>`;
  $("ro").onclick = () => drawRoutes(routes(B.piece[i], true), "склад → выезд");
  $("ri").onclick = () => drawRoutes(routes(B.piece[i], false), "выезд → склад");
  if ($("alt-go")) $("alt-go").onclick = () => showBuilding(alt, true);
}
function drawRoutes(res, title) { routesShown = res; M.request();
  $("rt").innerHTML = `${title}: ` + res.map((x, k) => `<span class="dot" style="background:${EXIT_COLORS[k]}"></span>${esc(D.exits[k].name)} ${x ? f0(x.time) + " мин" : "нет пути"}`).join(" · "); }
function showNoBuilding(lat, lon, note) {
  current = -1; routesShown = null; zoneHi = null; pin = [lat, lon]; M.request();
  const best = bestNear(lat, lon, CFG.no_building_radius_km * 1000, profile, -1, 3);
  card.innerHTML = `<p><b>Здесь нет здания.</b> Балл ставим только зданиям.${note ? " " + esc(note) : ""}</p>
    <h3>Лучшие здания в радиусе ${CFG.no_building_radius_km} км</h3>
    ${best.length ? `<ol class="list">${best.map(j => `<li>${esc(addrOf(j))} — <b>${f0(profileScore(j, profile))}</b> <button class="small" data-j="${j}">показать</button></li>`).join("")}</ol>` : `<p class="hint">Рядом нет оценённых зданий.</p>`}`;
  card.querySelectorAll("button[data-j]").forEach(b => b.onclick = () => showBuilding(+b.dataset.j, true));
}

// ---------- поиск по адресу ----------
const ABBR = [["улица","ул"],["ул.","ул"],["проспект","пр-т"],["просп.","пр-т"],["пр.","пр-т"],["переулок","пер"],["пер.","пер"],
  ["проезд","пр-д"],["шоссе","ш"],["ш.","ш"],["площадь","пл"],["пл.","пл"],["тракт","тр"],["бульвар","б-р"],["набережная","наб"],
  ["тупик","туп"],["дом",""],["д.",""],["г.",""],["город",""],["саратов",""]];
function normAddr(s) {   // как build_model.norm_address
  s = s.toLowerCase().replace(/ё/g, "е");
  for (const ch of ",;\"«»()") s = s.split(ch).join(" ");
  s = s.split(".").join(". ");
  const words = [];
  for (let w of s.split(/\s+/)) { if (!w) continue;
    for (const [a, b] of ABBR) if (w === a || w === a.replace(/\.$/, "")) { w = b; break; }
    if (w) words.push(w); }
  return words.join(" ");
}
let addrNorm = null;
function searchBuildings(q, limit) {
  if (!addrNorm) addrNorm = B.addr.map((a, i) => (a || B.name[i]) ? normAddr(a + " " + B.name[i]) : "");
  const t = normAddr(q).split(" ").filter(Boolean); if (!t.length) return [];
  const hits = [];
  for (let i = 0; i < NB; i++) { const a = addrNorm[i]; if (!a) continue; const ws = a.split(" ");
    if (t.every(x => ws.some(w => w === x || (w.startsWith(x) && !/^\d+$/.test(x))))) hits.push(i); }
  hits.sort((a, b) => (addrNorm[a].length - addrNorm[b].length) || (a - b));
  return hits.slice(0, limit);
}
const sIn = $("search"), sugg = $("sugg");
let suggIdx = [], act = -1;
sIn.addEventListener("input", () => { suggIdx = sIn.value.trim().length >= 2 ? searchBuildings(sIn.value, 8) : []; act = -1; renderSugg(); });
function renderSugg() {
  if (!sIn.value.trim()) { sugg.style.display = "none"; return; }
  sugg.innerHTML = suggIdx.map((i, k) => `<div data-i="${i}" class="${k === act ? "act" : ""}">${esc(addrOf(i))}${B.name[i] && B.addr[i] ? " · " + esc(B.name[i]) : ""} — <b>${f0(profileScore(i, profile))}</b></div>`).join("")
    + `<div data-nom="1">Искать «${esc(sIn.value)}» в Nominatim (интернет)</div>`;
  sugg.style.display = "block";
  sugg.querySelectorAll("div").forEach(d => d.onclick = () => d.dataset.nom ? nominatim(sIn.value) : pick(+d.dataset.i));
}
function pick(i) { sugg.style.display = "none"; sIn.value = addrOf(i); showBuilding(i, true); }
sIn.addEventListener("keydown", ev => {
  if (ev.key === "ArrowDown") { act = Math.min(act + 1, suggIdx.length - 1); renderSugg(); ev.preventDefault(); }
  else if (ev.key === "ArrowUp") { act = Math.max(act - 1, -1); renderSugg(); ev.preventDefault(); }
  else if (ev.key === "Enter") { if (act >= 0) pick(suggIdx[act]); else if (suggIdx.length) pick(suggIdx[0]); else nominatim(sIn.value); }
  else if (ev.key === "Escape") sugg.style.display = "none";
});
document.addEventListener("click", ev => { if (!ev.target.closest("#search-wrap")) sugg.style.display = "none"; });
// Nominatim: не чаще 1 запроса в секунду, кэш, только рамка Саратова; привязка к зданию в 50 м
let lastNom = 0;
async function nominatim(q) {
  sugg.style.display = "none"; if (!q.trim()) return;
  const key = "nom2:" + q.trim().toLowerCase(); let res = null;
  try { const c = localStorage.getItem(key); if (c) res = JSON.parse(c); } catch (e) {}
  if (!res) {
    const wait = 1100 - (Date.now() - lastNom); if (wait > 0) await new Promise(r => setTimeout(r, wait)); lastNom = Date.now();
    card.innerHTML = `<p class="hint">Ищу «${esc(q)}» в Nominatim…</p>`;
    try {
      const url = "https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&accept-language=ru&bounded=1&viewbox=45.75,51.72,46.20,51.40&q=" + encodeURIComponent(q + ", Саратов");
      const r = await fetch(url, { headers: { "Accept": "application/json" } }); const j = await r.json();
      res = j.length ? { lat: +j[0].lat, lon: +j[0].lon, name: j[0].display_name } : { none: true };
      try { localStorage.setItem(key, JSON.stringify(res)); } catch (e) {}
    } catch (e) { card.innerHTML = `<p>Nominatim недоступен (нужен интернет). Попробуйте ввести адрес как в OSM: «улица, номер дома».</p>`; return; }
  }
  if (res.none) { card.innerHTML = `<p>Адрес «${esc(q)}» не найден ни среди зданий OSM, ни в Nominatim.</p>`; return; }
  let i = buildingAt(res.lat, res.lon);
  if (i < 0) { const c = near(res.lat, res.lon, CFG.address_snap_m).sort((a, b) => distM(B.lat[a], B.lon[a], res.lat, res.lon) - distM(B.lat[b], B.lon[b], res.lat, res.lon)); if (c.length) i = c[0]; }
  if (i >= 0) showBuilding(i, true); else { M.setView([res.lat, res.lon], 16); showNoBuilding(res.lat, res.lon, `Nominatim: ${res.name}`); }
}

// ---------- зоны ----------
const ZC = CFG.zones.cell_m;
function zoneRects(z) { return z.cells.map(([i, j]) => [[j * ZC / KY, i * ZC / KX], [(j + 1) * ZC / KY, (i + 1) * ZC / KX]]); }
function showZone(k) {
  const z = D.zones[k]; current = -1; routesShown = null; pin = null; zoneHi = zoneRects(z);
  let s = 90, n = -90, w = 180, e = -180; for (const r of zoneHi) { s = Math.min(s, r[0][0]); n = Math.max(n, r[1][0]); w = Math.min(w, r[0][1]); e = Math.max(e, r[1][1]); }
  M.fitBounds(s, w, n, e, 16);
  const ex = explain(z.best), bd = badgeOf(z.score);
  card.innerHTML = `<span class="badge" style="background:${bd.color}">${bd.label}</span> <b>Зона ${k + 1}</b>
    <div class="total">${f0(z.score)} / 100 <span class="meta">лучшее здание · в среднем ${z.mean == null ? "—" : f0(z.mean)} (нежилые)</span></div>
    <div class="meta">Улицы: <b>${esc(z.streets)}</b><br>Площадь ≈ <b>${f0(z.area)} га</b> · подходящих зданий (≥ ${CFG.zones.suitable_score}): <b>${z.nSuitable}</b> · отличных (≥ ${CFG.zones.good_score}): <b>${z.nGood}</b></div>
    <h3>Время фуры от лучшего здания</h3>${timesHtml(ex.v)}
    <h3>Почему</h3><ul class="list">${ex.pros.map(t => `<li>${esc(t)}</li>`).join("")}</ul>
    ${ex.warnings.length ? `<h3>Предупреждения</h3><ul class="list warn">${ex.warnings.map(t => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}
    <h3>Топ-3 здания</h3><ol class="list">${z.top3.map(j => `<li>${esc(addrOf(j))} — <b>${f0(profileScore(j, "universal"))}</b> <button class="small" data-j="${j}">открыть</button></li>`).join("")}</ol>
    <p class="hint">Зоны посчитаны для профиля «Универсальный».</p>${UNKNOWN}`;
  card.querySelectorAll("button[data-j]").forEach(b => b.onclick = () => showBuilding(+b.dataset.j, true));
}
D.zones.slice(0, CFG.zones.top_n).forEach((z, k) => {
  const tr = document.createElement("tr"); tr.className = "zone-row"; tr.tabIndex = 0;
  tr.innerHTML = `<td><span class="znum">${k + 1}</span></td><td>${esc(z.streets || addrOf(z.best))}</td><td class="num"><b>${f0(z.score)}</b></td>`;
  tr.onclick = () => showZone(k); tr.onkeydown = ev => { if (ev.key === "Enter") showZone(k); };
  document.querySelector("#zones tbody").appendChild(tr);
});

// ---------- слои ----------
["l-bld", "l-top", "l-zones"].forEach(id => $(id).onchange = () => M.request());
$("l-osm").onchange = ev => { M.tilesOn = ev.target.checked; M.request(); };
$("model-note").innerHTML = `Модель: ${esc(D.model.name)}, проверка на незнакомых районах: ROC-AUC ${D.model.auc} (формула ${D.model.formulaAuc}), AP ${D.model.ap} (формула ${D.model.formulaAp}). Расчёт ${esc(D.model.date)}.
  Экспертная проверка: ${esc(typeof D.model.expert === "string" ? D.model.expert : "есть, см. отчёт")}. Время в пути — модель загруженности из Colab «модель дорог». Карта нарисована без сторонних библиотек; подложка, дороги и здания: © участники OpenStreetMap.`;
setProfile(profile);
window.WH = { profileScore, explain, valuesFor, buildingAt, bestNear, searchBuildings, normAddr, addrOf, showBuilding, showZone, M };
</script>
</body>
</html>
"""

LABEL_HTML = r"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Разметка зданий</title>
<style>
:root { --bg:#f4f3ef; --ink:#1f2429; --muted:#5f6771; --line:#dedbd2; --font:"Segoe UI", system-ui, sans-serif; }
* { box-sizing: border-box; } html, body { margin: 0; height: 100%; font: 14px/1.45 var(--font); color: var(--ink); background: var(--bg); }
#app { display: grid; grid-template-columns: 400px 1fr; height: 100%; }
@media (max-width: 820px) { #app { grid-template-columns: 1fr; grid-template-rows: 60% 40%; } }
aside { overflow-y: auto; background: #fff; border-right: 1px solid var(--line); padding: 14px 16px; }
#map { height: 100%; } h1 { font-size: 18px; margin: 0 0 6px; } .hint { color: var(--muted); font-size: 13px; }
.btns { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; margin: 10px 0; }
.btns button { padding: 10px; border: 1px solid var(--line); border-radius: 8px; background: #fff; font: 700 14px var(--font); cursor: pointer; }
.btns button.on { outline: 3px solid var(--ink); }
.g { color: #1a7f37; } .m { color: #b7791f; } .b { color: #b42318; } .u { color: var(--muted); }
.nav { display: flex; gap: 6px; margin: 6px 0; } .nav button, .tools button { padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; background: var(--bg); cursor: pointer; font: 600 12px var(--font); }
input[type=text], textarea { width: 100%; padding: 6px 8px; border: 1px solid var(--line); border-radius: 6px; font: 13px var(--font); }
.bar { height: 6px; background: #e8e5dc; border-radius: 3px; overflow: hidden; margin: 4px 0 10px; } .bar span { display: block; height: 100%; background: #1a7f37; }
ol { padding-left: 20px; font-size: 13px; max-height: 260px; overflow-y: auto; } li.cur { font-weight: 700; } li { cursor: pointer; }
.box { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fcfbf8; font-size: 13px; }
/*MAPCSS*/
</style>
</head>
<body>
<div id="app">
<aside>
  <h1>Разметка: подходит ли здание под склад?</h1>
  <p class="hint">Оцените здание по своему опыту: подъезд для фуры, соседи, выезды, само здание. Балл модели скрыт, чтобы не подсказывать. Оценки сохраняются в этом браузере; в конце нажмите «Скачать оценки (JSON)» и передайте файл — его превратит в Excel скрипт <code>import_labels.py</code>.</p>
  <label class="hint">Кто оценивает: <input type="text" id="who" placeholder="имя"></label>
  <div class="bar"><span id="prog"></span></div><div class="hint" id="progt"></div>
  <div class="box" id="info"></div>
  <div class="btns">
    <button data-l="Хорошо" class="g">Хорошо (1)</button><button data-l="Средне" class="m">Средне (2)</button>
    <button data-l="Плохо" class="b">Плохо (3)</button><button data-l="Не знаю" class="u">Не знаю (4)</button>
  </div>
  <textarea id="comment" rows="2" placeholder="Комментарий (необязательно): почему так"></textarea>
  <div class="nav"><button id="prev">← Назад</button><button id="next">Дальше →</button><button id="skip">К неоценённому</button></div>
  <div class="tools"><button id="export">Скачать оценки (JSON)</button> <a href="index.html" class="hint">к карте</a></div>
  <h3 style="font-size:13px">Все здания для разметки</h3><ol id="list"></ol>
</aside>
<div id="map"></div>
</div>
<script src="map_data.js"></script>
<script>
/*COMMON*/
/*ENGINE*/
const C = []; for (let i = 0; i < NB; i++) if (B.cand[i]) C.push(i);
const KEY = "wh-labels-v1";
let labels = {}; try { labels = JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { labels = {}; }
let who = ""; try { who = localStorage.getItem(KEY + "-who") || ""; } catch (e) {}
const whoEl = document.getElementById("who"); whoEl.value = who;
whoEl.oninput = () => { who = whoEl.value; try { localStorage.setItem(KEY + "-who", who); } catch (e) {} };
function save() { try { localStorage.setItem(KEY, JSON.stringify(labels)); } catch (e) {} }
const M = new MiniMap(document.getElementById("map"), { center: [51.56, 46.0], zoom: 12, tiles: location.protocol !== "file:",
  attribution: "© участники OpenStreetMap" });
let pos = 0, neigh = [];
M.drawFn = c => {
  for (const j of neigh) { M.path(poly(j)); c.closePath(); c.fillStyle = B.mask[j] & BITS.residential_type ? "rgba(217,199,163,.6)" : "rgba(154,164,177,.55)"; c.fill(); c.strokeStyle = "#666"; c.lineWidth = 0.6; c.stroke(); }
  if (C.length) { M.path(poly(C[pos])); c.closePath(); c.fillStyle = "rgba(180,35,24,.25)"; c.fill(); c.strokeStyle = "#b42318"; c.lineWidth = 3; c.stroke(); }
};
function show(k) {
  pos = (k + C.length) % C.length; const i = C[pos], v = valuesFor(i);
  neigh = near(B.lat[i], B.lon[i], 400); M.setView([B.lat[i], B.lon[i]], 17);
  const t = CFG.exits.names.filter(k => v.times[k] != null).map(k => `${k} ${f0(v.times[k])} мин`).join(", ");
  document.getElementById("info").innerHTML = `<b>${pos + 1} / ${C.length}. ${esc(addrOf(i))}</b><br>${B.name[i] ? esc(B.name[i]) + " — " : ""}${esc(D.types[B.type[i]])}, ${B.area[i].toLocaleString("ru")} м²<br>
    Фуре до выездов: ${esc(t) || "нет пути"}<br>Последняя миля до магистрали: ${r10(v.lm_len)} м, из них по жилым улицам и дворам ${r10(v.lm_yard)} м<br>
    Жилых домов в 200 м: ${f0(v.res_n_200)} · до школы/детсада ${r10(v.d_school)} м<br>
    <a href="${osmUrl(i)}" target="_blank" rel="noopener">здание в OSM</a> ·
    <a href="https://yandex.ru/maps/?pt=${B.lon[i]},${B.lat[i]}&z=18&l=sat" target="_blank" rel="noopener">спутник (Яндекс)</a>`;
  const cur = labels[B.id[i]];
  document.querySelectorAll(".btns button").forEach(b => b.classList.toggle("on", !!cur && cur.label === b.dataset.l));
  document.getElementById("comment").value = cur ? cur.comment || "" : "";
  renderList();
}
function setLabel(l) { const i = C[pos];
  labels[B.id[i]] = { osm_id: B.id[i], label: l, comment: document.getElementById("comment").value, who, ts: new Date().toISOString(), address: addrOf(i) };
  save(); show(pos + 1); }
document.querySelectorAll(".btns button").forEach(b => b.onclick = () => setLabel(b.dataset.l));
document.getElementById("comment").onchange = () => { const i = C[pos]; if (labels[B.id[i]]) { labels[B.id[i]].comment = document.getElementById("comment").value; save(); } };
document.getElementById("prev").onclick = () => show(pos - 1);
document.getElementById("next").onclick = () => show(pos + 1);
document.getElementById("skip").onclick = () => { for (let k = 1; k <= C.length; k++) { const j = (pos + k) % C.length; if (!labels[B.id[C[j]]]) return show(j); } };
document.addEventListener("keydown", ev => { if (ev.target.tagName === "TEXTAREA" || ev.target.tagName === "INPUT") return;
  const m = { "1": "Хорошо", "2": "Средне", "3": "Плохо", "4": "Не знаю" }; if (m[ev.key]) setLabel(m[ev.key]);
  if (ev.key === "ArrowRight") show(pos + 1); if (ev.key === "ArrowLeft") show(pos - 1); });
function renderList() {
  const done = C.filter(i => labels[B.id[i]]).length;
  document.getElementById("prog").style.width = (100 * done / C.length) + "%";
  document.getElementById("progt").textContent = `Оценено ${done} из ${C.length}`;
  const ol = document.getElementById("list");
  ol.innerHTML = C.map((i, k) => { const l = labels[B.id[i]];
    return `<li data-k="${k}" class="${k === pos ? "cur" : ""}">${esc(addrOf(i))}${l ? ` — <span class="${{ "Хорошо": "g", "Средне": "m", "Плохо": "b" }[l.label] || "u"}">${esc(l.label)}</span>` : ""}</li>`; }).join("");
  ol.querySelectorAll("li").forEach(li => li.onclick = () => show(+li.dataset.k));
}
document.getElementById("export").onclick = () => {
  const blob = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), who, labels: Object.values(labels) }, null, 1)], { type: "application/json" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = `expert_labels_${(who || "anon").replace(/[^\wа-яё-]/gi, "_")}.json`; a.click();
};
if (C.length) show(0);
</script>
</body>
</html>
"""

CMD = r"""@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "serve.py" (
  echo Не найдены файлы карты рядом с этим файлом.
  echo Похоже, вы запустили его прямо из архива. Распакуйте архив целиком
  echo ^(правый клик - "Извлечь всё"^) и запустите этот файл из распакованной папки.
  pause
  exit /b
)
python serve.py
pause
"""

SERVE = r'''"""Открывает карту в браузере. Сервер раздаёт только эту папку и работает, пока открыто окно."""
import functools, http.server, os, socketserver, webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=HERE)
with socketserver.TCPServer(("127.0.0.1", 0), Handler) as httpd:      # 0 = любой свободный порт
    url = f"http://localhost:{httpd.server_address[1]}/index.html"
    print("Карта:", url)
    print("Разметка экспертами:", url.replace("index.html", "label.html"))
    print("Не закрывайте это окно, пока смотрите карту.")
    webbrowser.open(url)
    httpd.serve_forever()
'''


def page(template):
    return template.replace("/*COMMON*/", COMMON_JS).replace("/*ENGINE*/", ENGINE_JS).replace("/*MAPCSS*/", MAP_CSS)


def main(out=OUT):
    data = build_data()
    mdir = out / "map"
    mdir.mkdir(parents=True, exist_ok=True)
    if (mdir / "assets").exists():          # от старой версии на Leaflet
        shutil.rmtree(mdir / "assets")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (mdir / "map_data.js").write_text("window.MAP_DATA=" + payload + ";", encoding="utf-8")
    (mdir / "index.html").write_text(page(HTML), encoding="utf-8")
    (mdir / "label.html").write_text(page(LABEL_HTML), encoding="utf-8")
    (mdir / "Открыть карту складов.cmd").write_text(CMD, encoding="utf-8")
    (mdir / "serve.py").write_text(SERVE, encoding="utf-8")
    print(f"Карта: {mdir / 'index.html'} (данные {(mdir / 'map_data.js').stat().st_size / 1e6:.1f} МБ)")
    single = build_single_file(payload, out)
    print(f"Карта одним файлом: {single} ({single.stat().st_size / 1e6:.1f} МБ)")


def build_single_file(payload, out=OUT):
    """Вся карта в одном HTML (данные внутри) — открывается двойным щелчком, без сервера.
    Подложка OSM с диска не грузится — тогда рисуются свои дороги; остальное работает."""
    html = page(HTML).replace('<script src="map_data.js"></script>',
                              "<script>window.MAP_DATA=" + payload.replace("</", "<\\/") + ";</script>")
    html = html.replace('<a href="label.html" id="label-link">Разметка экспертами</a>',
                        "Разметка экспертами (label.html в папке out/map)")
    assert "map_data.js" not in html and "leaflet" not in html.lower()
    path = out / SINGLE_NAME
    path.write_text(html, encoding="utf-8")
    return path


if __name__ == "__main__":
    main()
