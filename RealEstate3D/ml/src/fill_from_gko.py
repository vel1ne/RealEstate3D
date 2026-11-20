"""Заполнение датасета промышленных и складских зданий (ГКО 2023) из официального перечня объектов.

Источник: «Перечень (здания)» для государственной кадастровой оценки 2023 года, опубликован на сайте
правительства Саратовской области (saratov.gov.ru, раздел ГБУ СО «Госкадастроценка», «Результаты обработки
Перечней объектов капитального строительства» от 25.05.2023), файл zdania250523.xlsx → ml/data/gko/.

Что заполняется (только из перечня, ничего не придумываем):
  D «Этажей»        — «Количество этажей (в том числе подземных)», как в перечне (иногда текст «1-2»);
  E «Год постройки» — «Год завершения строительства», если пусто — «Год ввода в эксплуатацию»;
  F «Адрес»         — «Адрес (текст)», сокращённый по образцу: «Саратов, ул Рабочая, д 139»;
  G «Координаты»    — геокодирование адреса (Nominatim / OpenStreetMap); ставятся ТОЛЬКО если найден
                       именно дом (а не улица или район), иначе пусто и пометка в журнале.
Объекты, которых нет в перечне, остаются пустыми (это не значит, что они сняты с учёта).
Исходный файл не меняется: результат — копия «…_заполнено.xlsx» рядом, плюс лист «Журнал заполнения».

Запуск (из папки ml):  python src/fill_from_gko.py "C:/.../261111_Dataset_prom_i_sklady_GKO_2023_Saratov.xlsx"
  --no-geocode   без координат;   --limit N   только N строк (проверка)
  --dadata       добрать координаты через DaData (ключ в ml/.env: DADATA_API_KEY=…), только точное попадание в дом
"""
import argparse, json, re, sys, time, urllib.parse, urllib.request
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import DATA  # noqa: E402

MATCHED = DATA / "gko" / "matched.json"
GKO_XLSX = DATA / "gko" / "zdania250523.xlsx"
GEO_CACHE = DATA / "geocode_gko_cache.json"
UA = "RealEstate3D-study/1.0 (student project, Saratov)"
COL = {"cn": 2, "floors": 4, "year": 5, "addr": 6, "coords": 7}
FIELDS = ["Кадастровый номер", "Адрес (текст)", "Количество этажей (в том числе подземных)", "Количество подземных этажей",
          "Год завершения строительства", "Год ввода в эксплуатацию", "Наименование объекта"]
AREA_BBOX = (51.25, 45.55, 51.85, 46.40)   # Саратов и Гагаринский (Саратовский) район: юг, запад, север, восток


def extract(cns):
    """Строки перечня для нужных кадастровых номеров → ml/data/gko/matched.json (≈ 5 минут на 800 тыс. строк)."""
    ws = openpyxl.load_workbook(GKO_XLSX, read_only=True).worksheets[0]
    out, idx = {}, None
    for i, r in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            idx = {h: list(r).index(h) for h in FIELDS}
            continue
        cn = str(r[0]).strip() if r[0] else ""
        if cn in cns:
            out[cn] = {h: (str(r[j]).strip() if r[j] is not None else None) for h, j in idx.items()}
    MATCHED.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    return out


DROP = re.compile(r"^(российская федерация|россия|\d{6}|саратовская обл(асть|\.)?|"
                  r"городской округ (город )?саратов|муниципальное образование город саратов|"
                  r"г\.?\s*о\.?\s*(город )?саратов)$", re.I)
CITY = re.compile(r"^(г\.?\s*саратов|город саратов|саратов г\.?|саратов)$", re.I)


def short_address(a):
    """«Саратовская область, г Саратов, ул Рабочая, д 139» → «Саратов, ул Рабочая, д 139» (как в образце)."""
    a = re.sub(r"\s+", " ", a or "").strip()
    parts = [p.strip() for p in a.split(",") if p.strip()]
    parts = [p for p in parts if not DROP.match(p)]
    parts = ["Саратов" if CITY.match(p) else p for p in parts]
    return ", ".join(parts)


def year_of(v):
    y = v.get("Год завершения строительства")
    if y:
        return y, "год завершения строительства"
    y = v.get("Год ввода в эксплуатацию")
    return (y, "год ввода в эксплуатацию") if y else (None, "")


def as_number(s):
    return int(s) if s and re.fullmatch(r"\d+", s) else s


# ---------------------------------------------------------------- геокодирование
TYPES = [(r"ул\.?|улица", "улица"), (r"пр-кт|просп\.?|проспект", "проспект"), (r"пр-д|проезд", "проезд"),
         (r"пер\.?|переулок", "переулок"), (r"пл\.?|площадь", "площадь"), (r"ш\.?|шоссе", "шоссе"),
         (r"туп\.?|тупик", "тупик"), (r"б-р|бульвар", "бульвар"), (r"тракт", "тракт"), (r"наб\.?|набережная", "набережная"),
         (r"мкр\.?|мкр-н|микрорайон", "микрорайон"), (r"кв-л|квартал", "квартал")]
HOUSE = re.compile(r"^(д|дом|зд|здание|влд|вл|владение)\.?\s*(№\s*)?(\d[\w/\-]*)$", re.I)


def clean_name(name):
    name = re.sub(r"^им\.?\s+", "", name.strip(), flags=re.I)
    name = re.sub(r"\s+[А-ЯЁ]\.\s*([А-ЯЁ]\.)?$", "", name)          # инициалы: «Попова А.С.» → «Попова»
    return name.strip(" .").title() if name.isupper() else name.strip(" .")


def query_variants(short):
    """Варианты запроса к геокодеру: улица + номер дома (без «д», «зд», «корп», «стр»), населённый пункт.
    Без номера дома (б/н, «в 0,5 км от…», промузел) — не геокодируем: точку честно не поставить."""
    parts = [re.sub(r"^(ул|пл|пер|пр)\.(?=\S)", r". ", p.strip()) for p in short.split(",")]
    street, house = None, None
    for p in parts:
        m = HOUSE.match(p)
        if m:
            house = m.group(3)
            continue
        for pat, full in TYPES:
            m = re.match(rf"^({pat})\s+(.+)$", p, re.I) or re.match(rf"^(.+?)\s+({pat})$", p, re.I)
            if m:
                first_is_type = re.fullmatch(pat, m.group(1), re.I)
                street = f"{full} {clean_name(m.group(2) if first_is_type else m.group(1))}"
                break
        if street is None:   # «Саратов, Сокурский тракт 19 км» и т. п. — без типа улицы не угадываем
            pass
    town = "Саратов"
    for p in parts:
        m = re.match(r"^(рп|р\.п\.|пос\.?|п\.?|с\.?|село|поселок|посёлок)\s+(.+)$", p, re.I)
        if m and "саратов" not in p.lower():
            town = clean_name(m.group(2))
    out = []
    if street and house:
        out.append({"street": f"{house} {street}", "city": town})
        out.append({"q": f"{street} {house}, {town}"})
    return out


_last = [0.0]


def geocode(short, cache):
    if short in cache:
        return cache[short]
    res = None
    for params in query_variants(short):
        wait = 1.1 - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {**params, "format": "jsonv2", "limit": 1, "countrycodes": "ru", "accept-language": "ru", "addressdetails": 1,
             "viewbox": f"{AREA_BBOX[1]},{AREA_BBOX[2]},{AREA_BBOX[3]},{AREA_BBOX[0]}", "bounded": 1})
        try:
            r = json.load(urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30))
        except Exception as e:
            return {"error": str(e)}
        if r:
            g = r[0]
            lat, lon = float(g["lat"]), float(g["lon"])
            house_level = bool((g.get("address") or {}).get("house_number"))
            inside = AREA_BBOX[0] <= lat <= AREA_BBOX[2] and AREA_BBOX[1] <= lon <= AREA_BBOX[3]
            res = {"lat": lat, "lon": lon, "house": house_level, "inside": inside, "name": g.get("display_name", ""),
                   "query": params}
            if house_level and inside:
                break
    cache[short] = res
    GEO_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    return res


# ---------------------------------------------------------------- DaData (адреса ФИАС/ГАР)
DADATA_CACHE = DATA / "geocode_dadata_cache.json"
DADATA_URL = "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address"
QC_GEO = {"0": "точные координаты дома", "1": "ближайший дом", "2": "улица", "3": "населённый пункт", "4": "город",
          "5": "координаты не определены"}


def dadata_key():
    """Ключ: переменная окружения DADATA_API_KEY или файл ml/.env со строкой DADATA_API_KEY=… (в git не попадает)."""
    import os
    k = os.environ.get("DADATA_API_KEY")
    env = Path(__file__).resolve().parents[1] / ".env"
    if not k and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DADATA_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"')
    return k


def geocode_dadata(full_addr, key, cache):
    """Подсказки DaData (бесплатно до 10 000 в день). Берём координаты только с qc_geo = 0 (точно дом)."""
    if full_addr in cache:
        return cache[full_addr]
    body = json.dumps({"query": full_addr, "count": 1, "locations": [{"region": "Саратовская"}]}).encode("utf-8")
    req = urllib.request.Request(DADATA_URL, data=body, headers={
        "Content-Type": "application/json", "Accept": "application/json", "Authorization": "Token " + key})
    try:
        r = json.load(urllib.request.urlopen(req, timeout=30))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}
    sug = r.get("suggestions") or []
    if not sug:
        res = None
    else:
        d = sug[0]["data"]
        res = {"value": sug[0]["value"], "qc_geo": d.get("qc_geo"), "lat": d.get("geo_lat"), "lon": d.get("geo_lon"),
               "house": d.get("house")}
    cache[full_addr] = res
    DADATA_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    time.sleep(0.1)
    return res


def dadata_pass(out_path, data):
    """Второй проход по уже заполненной таблице: координаты из DaData там, где OSM не нашёл дом."""
    key = dadata_key()
    if not key:
        raise SystemExit("Нет ключа DaData: создайте файл ml/.env со строкой DADATA_API_KEY=ваш_ключ")
    wb = openpyxl.load_workbook(out_path)
    ws, log = wb.worksheets[0], wb["Журнал заполнения"]
    by_row = {row[0].value: row for row in log.iter_rows(min_row=2)}
    if log.cell(1, 12).value is None:
        log.cell(1, 12).value = "Координаты DaData (что нашла)"
        log.column_dimensions["L"].width = 70
    cache = json.loads(DADATA_CACHE.read_text(encoding="utf-8")) if DADATA_CACHE.exists() else {}
    st = {"точно дом": 0, "не точно — пропущено": 0, "не найдено": 0, "ошибка": 0}
    for r in range(2, ws.max_row + 1):
        cn = ws.cell(r, COL["cn"]).value
        v = data.get(str(cn).strip()) if cn else None
        if v is None or ws.cell(r, COL["coords"]).value:
            continue
        g = geocode_dadata(v["Адрес (текст)"], key, cache)
        lr = by_row.get(r)
        if g and "error" in g:
            st["ошибка"] += 1
            txt = "ошибка: " + g["error"]
            if g["error"] in ("HTTP 401", "HTTP 403"):
                raise SystemExit("DaData не принимает ключ (" + g["error"] + "). Проверьте ключ в ml/.env")
        elif not g:
            st["не найдено"] += 1
            txt = "не найдено"
        elif g["qc_geo"] == "0" and g["lat"] and g["lon"]:
            ws.cell(r, COL["coords"]).value = f"{float(g['lat']):.6f}, {float(g['lon']):.6f}"
            st["точно дом"] += 1
            txt = "точно дом: " + g["value"]
            if lr:
                lr[9].value = ws.cell(r, COL["coords"]).value
        else:
            st["не точно — пропущено"] += 1
            txt = f"не поставлено ({QC_GEO.get(str(g['qc_geo']), g['qc_geo'])}): " + g["value"]
        if lr:
            log.cell(lr[0].row, 12).value = txt
    wb.save(out_path)
    print("DaData:", st)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("xlsx")
    ap.add_argument("--no-geocode", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--dadata", action="store_true", help="только добрать координаты через DaData в уже заполненной таблице")
    a = ap.parse_args()
    src = Path(a.xlsx)
    out_path = src.with_name(src.stem + "_заполнено" + src.suffix)
    if a.dadata:
        return dadata_pass(out_path, json.loads(MATCHED.read_text(encoding="utf-8")))
    wb = openpyxl.load_workbook(src)
    ws = wb.worksheets[0]
    rows = [r for r in range(2, ws.max_row + 1) if ws.cell(r, COL["cn"]).value]
    cns = {str(ws.cell(r, COL["cn"]).value).strip() for r in rows}
    data = json.loads(MATCHED.read_text(encoding="utf-8")) if MATCHED.exists() else extract(cns)
    geo = json.loads(GEO_CACHE.read_text(encoding="utf-8")) if GEO_CACHE.exists() else {}
    if "Журнал заполнения" in wb.sheetnames:
        del wb["Журнал заполнения"]
    log = wb.create_sheet("Журнал заполнения")
    log.append(["Строка", "Кадастровый номер", "Статус", "Адрес в перечне (полный)", "Этажей в перечне",
                "Подземных этажей", "Год", "Откуда год", "Наименование объекта", "Координаты", "Что нашёл геокодер"])
    todo = [r for r in rows if not ws.cell(r, COL["addr"]).value]
    if a.limit:
        todo = todo[:a.limit]
    st = {"заполнено из перечня": 0, "нет в перечне": 0, "координаты (дом)": 0, "геокодер не нашёл дом": 0}
    for n, r in enumerate(todo, 1):
        cn = str(ws.cell(r, COL["cn"]).value).strip()
        v = data.get(cn)
        if v is None:
            st["нет в перечне"] += 1
            log.append([r, cn, "нет в перечне ГКО от 25.05.2023 — оставлено пустым"])
            continue
        short = short_address(v["Адрес (текст)"])
        floors = v["Количество этажей (в том числе подземных)"]
        year, ysrc = year_of(v)
        ws.cell(r, COL["addr"]).value = short or None
        if floors:
            ws.cell(r, COL["floors"]).value = as_number(floors)
        if year:
            ws.cell(r, COL["year"]).value = as_number(year)
        st["заполнено из перечня"] += 1
        gtxt, coords = "", ""
        if short and not a.no_geocode and not ws.cell(r, COL["coords"]).value:
            g = geocode(short, geo)
            if g and "lat" in g and g["house"] and g["inside"]:
                coords = f"{g['lat']:.6f}, {g['lon']:.6f}"
                ws.cell(r, COL["coords"]).value = coords
                st["координаты (дом)"] += 1
                gtxt = g["name"]
            else:
                st["геокодер не нашёл дом"] += 1
                gtxt = ("ошибка: " + g["error"]) if g and "error" in g else \
                    ("найдено не здание, а: " + g["name"]) if g and "lat" in g else "не найдено"
        log.append([r, cn, "заполнено из перечня ГКО", v["Адрес (текст)"], floors, v["Количество подземных этажей"],
                    year, ysrc, v["Наименование объекта"], coords, gtxt])
        if n % 50 == 0:
            wb.save(out_path)
            print(f"  {n}/{len(todo)} {st}", flush=True)
    for col, w in zip("ABCDEFGHIJK", [8, 20, 34, 60, 10, 10, 8, 26, 34, 24, 60]):
        log.column_dimensions[col].width = w
    wb.save(out_path)
    print("готово:", out_path, st)


if __name__ == "__main__":
    main()
