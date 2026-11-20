"""Attach cadastral attributes to OSM buildings without changing their geometry."""

import argparse
from collections import Counter, defaultdict
import csv
import json
from math import cos, radians
from pathlib import Path
import re
import sqlite3
from tempfile import NamedTemporaryFile

from openpyxl import load_workbook
from shapely.geometry import Point, Polygon
from shapely.strtree import STRtree


DE = Path(__file__).resolve().parents[1]
OSM = DE.parent / "ml" / "data" / "osm" / "buildings.json"
DATABASE = DE / "data" / "processed" / "saratov_buildings.sqlite"
MAX_OFFSET_M = 15
METRES_X = 111320 * cos(radians(51.55))
METRES_Y = 110574
ROAD_TYPES = {
    "ул": "улица", "ул-ца": "улица", "пр-кт": "проспект", "пр-т": "проспект",
    "просп": "проспект", "пр-д": "проезд", "пер": "переулок", "пл": "площадь",
    "наб": "набережная", "ш": "шоссе", "б-р": "бульвар", "тр": "тракт",
}
ROAD_TYPES.update({word: word for word in (
    *ROAD_TYPES.values(), "тупик", "аллея", "линия", "спуск", "переезд",
)})
HOUSE_MARKER = re.compile(r"(?:^|[ ,])(?:дом|д|здание|зд|владение|вл)\.?\s*№?\s*(?=\d)")
CITY = re.compile(r"(?:(?:город|г\.?)\s+)?саратов(?:\s+(?:город|г\.?))?")


def clean(value):
    return str(value or "").casefold().replace("ё", "е").strip()


def street_key(street):
    value = clean(street)
    value = re.sub(r"\b(?:имени|им)\.?\s+", "", value)
    value = re.sub(r"\s+(?:[а-я]\.\s*){1,3}$", "", value)
    value = re.sub(r"(?<=\d)-(?:й|я|ая|ый|ой)\b", "", value)
    words = re.findall(r"[а-яa-z0-9]+(?:-[а-яa-z0-9]+)*", value)
    if not words:
        return None
    kind = ROAD_TYPES.get(words[0]) or ROAD_TYPES.get(words[-1])
    if kind:
        words.pop(0 if words[0] in ROAD_TYPES else -1)
    return kind, " ".join(words)


def house_key(house):
    value = clean(house)
    value = re.sub(r"\s*(?:строение|стр\.?)\s*(?=\d)", "с", value)
    value = re.sub(r"\s*(?:корпус|корп\.?)\s*(?=\d)", "к", value)
    value = re.sub(r"[\s,]+", "", value)
    value = value.translate(str.maketrans("abcehkmoptxy", "авсенкмортху"))
    return value if re.fullmatch(r"\d+[а-я]?(?:[/\-]\d+[а-я]?)?(?:[ск]\d+[а-я]?)*", value) else None


def address_key(address):
    parts = [part.strip() for part in clean(address).split(",")]
    if re.fullmatch(r"саратовская (?:область|обл\.?)", parts[0]):
        parts.pop(0)
    if len(parts) < 2 or not CITY.fullmatch(parts[0]):
        return None
    body = ", ".join(parts[1:])
    marker = HOUSE_MARKER.search(body)
    if marker:
        street, house = body[:marker.start()].rstrip(", "), body[marker.end():]
    else:
        street, sep, house = body.rpartition(",")
        if not sep:
            return None
    street, house = street_key(street), house_key(house)
    return (street, house) if street and street[1] and house else None


def coordinate(value):
    try:
        lat, lon = map(float, str(value).split(","))
    except ValueError:
        return None, None
    return (lat, lon) if 51 < lat < 52 and 45 < lon < 47 else (None, None)


def outline(flat):
    x = y = 0
    points = []
    for dx, dy in zip(flat[::2], flat[1::2]):
        x += dx
        y += dy
        points.append((x * METRES_X / 1e6, y * METRES_Y / 1e6))
    return Polygon(points)


def specific_type(name):
    value = clean(name)
    groups = {
        "warehouse": r"\bсклад[а-я]*\b|\bхранилище\b",
        "production": r"\b(?:цех[а-я]*|производственн[а-я]*|завод[а-я]*|фабрик[а-я]*|промышленн[а-я]*)\b",
        "retail": r"\b(?:магазин[а-я]*|супермаркет[а-я]*|торгов[а-я]*)\b",
        "residential": r"\b(?:жилой дом|жилое здание|многоквартирный дом|общежитие)\b",
    }
    kinds = [kind for kind, pattern in groups.items() if re.search(pattern, value)]
    if len(kinds) != 1:
        return None, None
    kind = kinds[0]
    label = "Цех" if kind == "production" and re.search(r"\bцех[а-я]*\b", value) else None
    return kind, label


def load_osm(path):
    with path.open(encoding="utf-8") as stream:
        snapshot = json.load(stream)
    index = defaultdict(list)
    buildings, polygons = [], []
    for row in snapshot["rows"]:
        osm_id, _, _, _, kind, street, house, _, _, flat = row
        if len(flat) < 8:
            continue
        polygon = outline(flat)
        if not polygon.is_valid or polygon.is_empty:
            continue
        if street and house:
            index[(street_key(street), house_key(house))].append(len(buildings))
        buildings.append((osm_id, kind))
        polygons.append(polygon)
    return index, buildings, STRtree(polygons)


def match(address, lat, lon, index, tree):
    if not address or clean(address) == "объект не найден":
        return None, None, "Нет адреса"
    key = address_key(address)
    if not key:
        return None, None, "Адрес без однозначного номера дома или вне Саратова"
    if lat is None:
        return None, None, "Нет пригодных координат"
    point = Point(lon * METRES_X, lat * METRES_Y)
    candidates = index.get(key, [])
    nearby = [(i, tree.geometries[i].distance(point)) for i in candidates]
    nearby = [(i, distance) for i, distance in nearby if distance <= MAX_OFFSET_M]
    if not nearby:
        reason = "Нет контура OSM с таким адресом" if not candidates else "Точка далеко от контура с таким адресом"
        return None, None, reason
    if len(nearby) != 1:
        return None, None, "Рядом несколько контуров с таким адресом"
    i, distance = nearby[0]
    if any(j != i for j in tree.query(point, predicate="within")):
        return None, None, "Точка внутри другого контура OSM"
    return i, round(distance, 2), None


def read_records(path, osm_path):
    index, buildings, tree = load_osm(osm_path)
    book = load_workbook(path, read_only=True, data_only=True)
    try:
        objects = {r[1]: r[8] for r in book["Журнал заполнения"].iter_rows(min_row=2, values_only=True) if r[1]}
        manual = {
            r[1] for r in book["Сравнение"].iter_rows(min_row=2, values_only=True)
            if "проверить вручную" in clean(r[8])
        }
        records = []
        for row_number, row in enumerate(book.worksheets[0].iter_rows(min_row=2, values_only=True), 2):
            _, cadastral, area, floors, year, address, coords, *_ = row
            if not cadastral:
                continue
            lat, lon = coordinate(coords)
            idx, distance, reason = match(address, lat, lon, index, tree)
            if idx is not None and cadastral in manual:
                idx, distance, reason = None, None, "Расхождение координат отмечено при сверке DaData"
            name = objects.get(cadastral)
            kind, label = specific_type(name)
            osm_id, osm_type = buildings[idx] if idx is not None else (None, None)
            records.append({
                "source_row": row_number, "cadastral_number": cadastral, "address": address,
                "source_lat": lat, "source_lon": lon, "area_m2": area, "floors": floors, "year_built": year,
                "source_name": name, "category_gko": kind, "type_detail": label, "osm_type": osm_type,
                "osm_id": osm_id, "offset_m": distance, "review_reason": reason,
            })
    finally:
        book.close()
    counts = Counter(r["osm_id"] for r in records if r["osm_id"] is not None)
    for record in records:
        if counts[record["osm_id"]] > 1:
            record.update(osm_id=None, osm_type=None, offset_m=None,
                          review_reason="Несколько кадастровых записей на один контур")
    return records


def save_database(path, records, source):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, suffix=".sqlite", delete=False) as stream:
        temp = Path(stream.name)
    try:
        db = sqlite3.connect(temp)
        try:
            with db:
                db.executescript("""
                    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE building_registry (
                        source_row INTEGER PRIMARY KEY,
                        cadastral_number TEXT NOT NULL,
                        address TEXT, source_lat REAL, source_lon REAL,
                        area_m2 REAL, floors INTEGER, year_built INTEGER,
                        source_name TEXT, category_gko TEXT, type_detail TEXT, osm_type TEXT,
                        osm_id INTEGER UNIQUE, offset_m REAL, review_reason TEXT,
                        CHECK ((osm_id IS NULL) = (review_reason IS NOT NULL))
                    );
                    CREATE VIEW building_manual_review AS
                        SELECT * FROM building_registry WHERE osm_id IS NULL;
                """)
                db.executemany("INSERT INTO metadata VALUES (?, ?)", (
                    ("source_file", source.name),
                    ("osm_id_encoding", "way: positive; relation: negative"),
                    ("source_coordinates", "WGS84"),
                    ("max_offset_m", str(MAX_OFFSET_M)),
                ))
                columns = tuple(records[0])
                db.executemany(
                    f"INSERT INTO building_registry ({','.join(columns)}) VALUES ({','.join(':' + c for c in columns)})",
                    records,
                )
        finally:
            db.close()
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--osm", type=Path, default=OSM)
    parser.add_argument("--output", type=Path, default=DATABASE)
    parser.add_argument("--review-csv", type=Path, help="Экспорт строк для ручной проверки")
    args = parser.parse_args()
    records = read_records(args.workbook, args.osm)
    if not records:
        parser.error("Нет кадастровых записей для импорта")
    save_database(args.output, records, args.workbook)
    if args.review_csv:
        fields = ("source_row", "cadastral_number", "address", "source_lat", "source_lon", "review_reason")
        with args.review_csv.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fields, delimiter=";", extrasaction="ignore")
            writer.writeheader()
            writer.writerows(record for record in records if record["review_reason"])
    print(Counter(record["review_reason"] or "Привязано" for record in records))


if __name__ == "__main__":
    main()
