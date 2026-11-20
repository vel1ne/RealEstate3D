"""Заполнение датасета промышленных и складских зданий (ГКО 2023): этажи, год, адрес, координаты.

Источники (ничего не придумываем):
  • этажи, год постройки (если пусто — год ввода в эксплуатацию), адрес — НСПД (nspd.gov.ru, публичная
    кадастровая карта Росреестра) по кадастровому номеру; ответ каждого объекта сохраняется в ml/data/nspd/;
  • координаты — геокодирование адреса через Nominatim (OpenStreetMap), не чаще 1 запроса в секунду.
Если НСПД объект не находит — в «Адрес» пишется «ОБЪЕКТ НЕ НАЙДЕН» (строку не удаляем).
Исходный файл не меняется: результат — копия с суффиксом «_заполнено» рядом с исходным.

У nspd.gov.ru сертификат от российского удостоверяющего центра (Russian Trusted Root CA), которого нет
в стандартных хранилищах. Путь к файлу этого корневого сертификата передаётся параметром --cacert
(проверка сертификата остаётся включённой).

Запуск (из папки ml), вариант «выгрузка в своём браузере»:
  1) python src/fill_cadastre.py "C:/.../261111_Dataset_prom_i_sklady_GKO_2023_Saratov.xlsx" --make-js
     → out/nspd_export.js; запустить его в браузере на https://nspd.gov.ru/map (F12 → Консоль) → nspd_export.json
  2) python src/fill_cadastre.py "C:/.../261111_Dataset_prom_i_sklady_GKO_2023_Saratov.xlsx" --from-json nspd_export.json
Вариант «скрипт сам»: --cacert russian_trusted_root_ca.pem (сейчас API НСПД отвечает 403 на запросы не из браузера)
  --limit 20          только первые 20 пустых строк (проверка)
  --no-geocode        без координат
"""
import argparse, json, re, ssl, sys, time, urllib.parse, urllib.request
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import DATA  # noqa: E402

NSPD_URL = "https://nspd.gov.ru/api/geoportal/v2/search/geoportal?thematicSearchId=1&query="
CACHE = DATA / "nspd"
GEO_CACHE = DATA / "geocode_cache.json"
UA = "RealEstate3D-study/1.0 (student project, Saratov)"
NOT_FOUND = "ОБЪЕКТ НЕ НАЙДЕН"
COL = {"cn": 2, "floors": 4, "year": 5, "addr": 6, "coords": 7}   # B, D, E, F, G


def nspd(cn, ctx, pause=1.5):
    """Ответ НСПД по кадастровому номеру (с кэшем на диске)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (cn.replace(":", "_") + ".json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    req = urllib.request.Request(NSPD_URL + urllib.parse.quote(cn), headers={
        "User-Agent": "Mozilla/5.0", "Referer": "https://nspd.gov.ru/map", "Accept": "application/json"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=40, context=ctx) as r:
                data = json.loads(r.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:          # НСПД отвечает 404, если объекта нет
                data = {"_not_found": True, "_http": 404}
                break
            err = f"HTTP {e.code}"
        except Exception as e:  # сеть, таймаут
            err = str(e)
        time.sleep(5 * (attempt + 1))
    else:
        return {"_error": err}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    time.sleep(pause)
    return data


def pick(options, *keys):
    for k in keys:
        v = options.get(k)
        if v not in (None, "", "-"):
            return v
    return None


def parse(data, cn):
    """→ (адрес, этажи, год, источник года) или None, если объекта нет."""
    feats = (data.get("data") or {}).get("features") or []
    feats = [f for f in feats if ((f.get("properties") or {}).get("options") or {}).get("cad_num", cn) == cn] or feats
    if not feats:
        return None
    o = feats[0].get("properties", {}).get("options", {})
    addr = pick(o, "readable_address", "address_readable_address", "address")
    floors = pick(o, "floors", "floors_count")
    year = pick(o, "year_built")
    src = "год постройки"
    if year is None:
        year = pick(o, "year_commisioning", "year_commissioning")
        src = "год ввода" if year is not None else ""
    return addr, floors, year, src


def short_address(a):
    """Как в образце: «Саратов, ул Рабочая, д 139» — убираем страну, индекс и область, сокращаем «г. Саратов»."""
    if not a:
        return a
    parts = [p.strip() for p in str(a).split(",") if p.strip()]
    drop = re.compile(r"^(российская федерация|россия|\d{6}|саратовская обл(асть|\.)?|обл(асть)? саратовская|"
                      r"городской округ город саратов|г\.?о\.? город саратов|муниципальное образование.*)$", re.I)
    parts = [p for p in parts if not drop.match(p)]
    parts = [re.sub(r"^(г\.?|город)\s*Саратов$", "Саратов", p, flags=re.I) for p in parts]
    return ", ".join(parts)


def to_int(v):
    try:
        return int(float(str(v).split()[0].replace(",", ".")))
    except (ValueError, IndexError):
        return v


_last = [0.0]


def geocode(addr, cache):
    if addr in cache:
        return cache[addr]
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    q = addr if "саратов" in addr.lower() else "Саратов, " + addr
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "ru", "accept-language": "ru"})
    try:
        res = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30))
    except Exception as e:
        return {"error": str(e)}
    out = {"lat": float(res[0]["lat"]), "lon": float(res[0]["lon"]), "type": res[0].get("addresstype") or res[0].get("type"),
           "name": res[0].get("display_name", "")} if res else None
    cache[addr] = out
    GEO_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return out


def load_export(path):
    """Ответы НСПД, сохранённые в браузере, → кэш ml/data/nspd/ (дальше скрипт работает без сети к НСПД)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    n = 0
    for cn, resp in d.items():
        if resp is None or "_error" in resp:
            continue
        (CACHE / (cn.replace(":", "_") + ".json")).write_text(json.dumps(resp, ensure_ascii=False), encoding="utf-8")
        n += 1
    print(f"из выгрузки браузера: {n} ответов НСПД", flush=True)


JS = r"""// Выгрузка из НСПД для датасета ГКО 2023. Запускать в СВОЁМ браузере на странице https://nspd.gov.ru/map
// (F12 → Консоль → вставить весь текст → Enter). Один запрос раз в 2 секунды; прогресс сохраняется,
// при повторном запуске продолжит с того же места. В конце скачается файл nspd_export.json.
(async () => {
  const CNS = __CNS__;
  const KEY = "nspd_export_v1";
  const res = JSON.parse(localStorage.getItem(KEY) || "{}");
  const todo = CNS.filter(c => !(c in res) || (res[c] && res[c]._error));
  console.log(`НСПД: всего ${CNS.length}, осталось ${todo.length}. Не закрывайте вкладку.`);
  for (let i = 0; i < todo.length; i++) {
    const cn = todo[i];
    try {
      const r = await fetch("/api/geoportal/v2/search/geoportal?thematicSearchId=1&query=" + encodeURIComponent(cn), { headers: { Accept: "application/json" } });
      if (r.status === 404) res[cn] = { _not_found: true, _http: 404 };
      else if (r.ok) { const j = await r.json(); const f = ((j.data || {}).features || []).slice(0, 3)
        .map(x => ({ properties: { options: (x.properties || {}).options || {} } })); res[cn] = { data: { features: f } }; }
      else res[cn] = { _error: "HTTP " + r.status };
    } catch (e) { res[cn] = { _error: String(e) }; }
    localStorage.setItem(KEY, JSON.stringify(res));
    if ((i + 1) % 25 === 0) console.log(`  ${i + 1} / ${todo.length}`);
    await new Promise(r => setTimeout(r, 2000));
  }
  const errs = Object.values(res).filter(v => v && v._error).length;
  console.log(`Готово. Ошибок: ${errs} (запустите скрипт ещё раз — повторит только их).`);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(res)], { type: "application/json" }));
  a.download = "nspd_export.json"; a.click();
})();
"""


def make_js(ws):
    from paths import OUT
    cns = [str(ws.cell(r, COL["cn"]).value).strip() for r in range(2, ws.max_row + 1)
           if ws.cell(r, COL["cn"]).value and not ws.cell(r, COL["addr"]).value]
    path = OUT / "nspd_export.js"
    path.write_text(JS.replace("__CNS__", json.dumps(cns)), encoding="utf-8")
    print(f"скрипт для браузера: {path} ({len(cns)} кадастровых номеров)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--cacert", help="корневой сертификат Russian Trusted Root CA (для запросов к НСПД из скрипта)")
    ap.add_argument("--from-json", help="файл nspd_export.json, выгруженный в браузере скриптом nspd_export.js")
    ap.add_argument("--make-js", action="store_true", help="только сделать out/nspd_export.js для браузера")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-geocode", action="store_true")
    a = ap.parse_args()
    src = Path(a.xlsx)
    out = src.with_name(src.stem + "_заполнено" + src.suffix)
    wb = openpyxl.load_workbook(out if out.exists() else src)   # продолжаем, если уже начинали
    ws = wb.worksheets[0]
    if a.make_js:
        make_js(ws)
        return
    if a.from_json:
        load_export(a.from_json)
    ctx = ssl.create_default_context(cafile=a.cacert) if a.cacert else None
    log = wb["Журнал заполнения"] if "Журнал заполнения" in wb.sheetnames else wb.create_sheet("Журнал заполнения")
    if log.max_row == 1 and log.cell(1, 1).value is None:
        log.append(["Строка", "Кадастровый номер", "Статус НСПД", "Адрес НСПД (полный)", "Этажи", "Год", "Откуда год",
                    "Геокодирование", "Найдено геокодером"])
    geo = json.loads(GEO_CACHE.read_text(encoding="utf-8")) if GEO_CACHE.exists() else {}
    todo = [r for r in range(2, ws.max_row + 1) if ws.cell(r, COL["cn"]).value and not ws.cell(r, COL["addr"]).value]
    if a.limit:
        todo = todo[:a.limit]
    print(f"строк без адреса: {len(todo)}", flush=True)
    stats = {"найдено": 0, "не найдено": 0, "ошибка": 0, "координаты": 0}
    for n, r in enumerate(todo, 1):
        cn = str(ws.cell(r, COL["cn"]).value).strip()
        data = nspd(cn, ctx)
        if "_error" in data:
            stats["ошибка"] += 1
            log.append([r, cn, "ошибка: " + data["_error"]])
            continue
        p = None if data.get("_not_found") else parse(data, cn)
        if p is None:
            ws.cell(r, COL["addr"]).value = NOT_FOUND
            stats["не найдено"] += 1
            log.append([r, cn, "не найден в НСПД"])
        else:
            addr, floors, year, ysrc = p
            if floors is not None:
                ws.cell(r, COL["floors"]).value = to_int(floors)
            if year is not None:
                ws.cell(r, COL["year"]).value = to_int(year)
            ws.cell(r, COL["addr"]).value = short_address(addr) if addr else None
            stats["найдено"] += 1
            gstat, gname = "", ""
            if addr and not a.no_geocode and not ws.cell(r, COL["coords"]).value:
                g = geocode(short_address(addr), geo)
                if g and "lat" in g:
                    ws.cell(r, COL["coords"]).value = f"{g['lat']:.6f}, {g['lon']:.6f}"
                    stats["координаты"] += 1
                    gstat, gname = f"найдено ({g['type']})", g["name"]
                else:
                    gstat = "не найдено" if g is None else "ошибка: " + g.get("error", "")
            log.append([r, cn, "найден", addr, floors, year, ysrc, gstat, gname])
        if n % 25 == 0:
            wb.save(out)
            print(f"  {n}/{len(todo)}  {stats}", flush=True)
    wb.save(out)
    print("готово:", out, stats)


if __name__ == "__main__":
    main()
