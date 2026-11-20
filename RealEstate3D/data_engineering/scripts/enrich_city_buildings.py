"""Build and match a city extract from the full Saratov GKO building workbook."""

import argparse
from collections import Counter, defaultdict
from io import BytesIO
import json
from pathlib import Path
import pickle
import re
import sqlite3
from tempfile import NamedTemporaryFile
from zipfile import ZipFile

from openpyxl import load_workbook
from shapely.geometry import Point
from shapely.strtree import STRtree

from link_buildings import (
    DATABASE, MAX_OFFSET_M, METRES_X, METRES_Y, OSM, address_key, clean, house_key, outline,
    specific_type, street_key,
)

CITY = re.compile(r"(?:г\.?\s*|город\s+)?саратов(?:\s+г\.?)?")
CITY_DATABASE = DATABASE.with_name("saratov_city_buildings.sqlite")
MANUAL_LINKS = DATABASE.parent.parent / "manual_building_links.json"
SCORED_BUILDINGS = OSM.parent.parent / "buildings_scored.pkl"
SGU_SOURCE = "https://www.sgu.ru/sveden/objects-old"
# Campus numbers and addresses agree with the names on these OSM footprints.
SGU_BUILDINGS = {
    36055377: (3, "Университетская улица", "40", 4640.30),
    36058469: (4, "Университетская улица", "59", 2134.90),
    35998859: (5, "Астраханская улица", "83", 5053.80),
    36058470: (7, "Большая Казачья улица", "120", 3161.70),
    36055376: (8, "Большая Казачья улица", "112А", 5896.40),
    102317557: (16, "улица Заулошнова", "3", 4743.00),
    91102110: (17, "улица Заулошнова", "5", 1627.40),
    86384617: (19, "Астраханская улица", "77", 12063.90),
}
FIELDS = {
    "cadastral_number": "Кадастровый номер",
    "list_name": "Наименование перечня",
    "address": "Адрес (текст)",
    "locality": "Наименование населённого пункта",
    "street": "Наименование улицы",
    "area_m2": "Площадь, кв.м",
    "year_built": "Год завершения строительства",
    "year_opened": "Год ввода в эксплуатацию",
    "purpose": "Назначение здания",
    "name": "Наименование объекта",
    "subgroup": "Наименование подгруппы",
    "floors": "Количество этажей (в том числе подземных)",
}


def text(value):
    return str(value).strip() if value is not None else ""


def city_address(address, locality):
    parts = [part.strip() for part in address.split(",")]
    for i, part in enumerate(parts):
        if CITY.fullmatch(clean(part)):
            return ", ".join(["Саратов", *parts[i + 1:]])
    if CITY.fullmatch(clean(locality)):
        return "Саратов, " + address
    return None


def normalized_street(street):
    kind, name = street
    words = name.split()
    ordinal = [word for word in words if word.isdecimal()]
    if len(ordinal) == 1 and len(words) > 1 and kind in {"проезд", "переулок", "тупик", "линия"}:
        name = " ".join([ordinal[0], *(word for word in words if word != ordinal[0])])
    return kind, name


def city_key(address):
    # A bare number sign is a house marker only when it starts the final address part.
    if address:
        address = re.sub(r",\s*№\s*(?=\d)", ", д ", address)
    key = address_key(address)
    if not key:
        return None
    street, house = key
    return normalized_street(street), house


def extract(workbook, destination):
    book = load_workbook(workbook, read_only=True, data_only=True)
    try:
        rows = book.worksheets[0].values
        headers = list(next(rows))
        columns = {key: headers.index(header) for key, header in FIELDS.items()}
        print("Чтение полного перечня ГКО", flush=True)
        records = []
        kinds = Counter()
        for number, row in enumerate(rows, 2):
            if number % 100000 == 0:
                print(f"Прочитано строк: {number:,}", flush=True)
            if not row[columns["cadastral_number"]]:
                continue
            addr = city_address(text(row[columns["address"]]), text(row[columns["locality"]]))
            if not addr:
                continue
            record = {key: row[i] for key, i in columns.items()}
            record["city_address"] = addr
            record["source_row"] = number
            records.append(record)
            kinds[text(record["list_name"])] += 1
    finally:
        book.close()
    if not records:
        raise ValueError("Не найдены записи по Саратову")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp")
    temporary.write_text(json.dumps(records, ensure_ascii=False, default=str), encoding="utf-8")
    temporary.replace(destination)
    print(f"Строк по Саратову: {len(records):,}. Виды перечня: {dict(kinds)}", flush=True)


def numeric_area(value):
    try:
        area = float(text(value).replace(" ", "").replace(",", "."))
    except ValueError:
        return None
    return area if 0 < area < float("inf") else None


def year(value):
    value = text(value)
    return int(value[:4]) if re.fullmatch(r"(?:1[0-9]{3}|20[0-9]{2})(?:-\d{2}(?:-\d{2})?)?", value) else None


def osm_attributes():
    result = {}
    for path in sorted((OSM.parent / "raw_buildings").glob("*.json")):
        with path.open(encoding="utf-8") as stream:
            elements = json.load(stream)["elements"]
        for element in elements:
            if element["type"] not in {"way", "relation"}:
                continue
            tags = element.get("tags", {})
            osm_id = -element["id"] if element["type"] == "relation" else element["id"]
            built = year(tags.get("start_date"))
            levels = tags.get("building:levels")
            if built or levels or tags.get("addr:city"):
                result[osm_id] = (built, levels, CITY.fullmatch(clean(tags.get("addr:city"))) is not None)
    return result


def prior_registry():
    if not DATABASE.is_file():
        return {}, set()
    db = sqlite3.connect(DATABASE.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        links = {row["osm_id"]: dict(row) for row in db.execute(
            "SELECT * FROM building_registry WHERE osm_id IS NOT NULL"
        )}
        excluded = {row[0] for row in db.execute("""
            SELECT cadastral_number FROM building_manual_review
            WHERE review_reason IN ('Расхождение координат отмечено при сверке DaData',
                'Точка далеко от контура с таким адресом', 'Точка внутри другого контура OSM',
                'Рядом несколько контуров с таким адресом', 'Несколько кадастровых записей на один контур')
        """)}
        return links, excluded
    finally:
        db.close()


def gko_category(record):
    kind, label = specific_type(record["name"])
    if kind:
        return kind, label
    purpose = clean(record["purpose"])
    if purpose in {"жилое", "жилой дом", "жилое здание", "многоквартирный дом", "многоквартирное"}:
        return "residential", "Многоквартирный дом" if purpose.startswith("многоквартир") else None
    return None, None


def campus_area(osm_id, street, house, name):
    match = SGU_BUILDINGS.get(osm_id)
    if match:
        number, expected_street, expected_house, area = match
        if (street, house, name) == (expected_street, expected_house,
                                   f"Саратовский государственный университет, корпус № {number}"):
            return area
    return None


def housing_records(path):
    if path is None:
        return []
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    columns = ("full_address", "region_name", "latitude", "longitude", "qc_geo", "cadastral_number",
               "gisgkh_guid", "building_year", "total_area")
    with ZipFile(path) as archive:
        member = next(name for name in archive.namelist() if name.endswith(".parquet") and "/" not in name)
        table = pq.ParquetFile(BytesIO(archive.read(member))).read(columns=columns)
    table = table.filter(pc.equal(table["region_name"], "Саратовская область"))
    result = []
    for row in table.to_pylist():
        address = city_address(text(row["full_address"]), "")
        key = city_key(address)
        if key:
            row["key"] = key
            row["city_address"] = address
            result.append(row)
    return result


def match_housing(housing, buildings, city_ids, by_address, links, excluded):
    if not housing:
        return {}
    polys, ids, osm_rows = [], [], {}
    for row in buildings:
        osm_id, *_, flat = row
        if osm_id not in city_ids:
            continue
        polygon = outline(flat)
        if polygon.is_valid and not polygon.is_empty:
            polys.append(polygon)
            ids.append(osm_id)
            osm_rows[osm_id] = row
    tree = STRtree(polys)
    geometry = dict(zip(ids, polys))
    numbers_by_osm = {osm_id: number for number, osm_id in links.items()}
    proposals = defaultdict(list)
    for row in housing:
        number = text(row["cadastral_number"])
        number = number if re.fullmatch(r"64:\d{2}:\d+:\d+", number) else None
        if number in excluded:
            continue
        addresses = by_address.get(row["key"], [])
        lat, lon = row["latitude"], row["longitude"]
        buildings_at_point = set()
        if row["qc_geo"] == "Точные координаты" and lat and lon:
            point = Point(lon * METRES_X, lat * METRES_Y)
            buildings_at_point = {ids[i] for i in tree.query(point, predicate="within")}
            nearby = [i for i in addresses if i in geometry and geometry[i].distance(point) <= MAX_OFFSET_M]
            if len(buildings_at_point) == 1:
                osm_id = next(iter(buildings_at_point))
                osm_row = osm_rows[osm_id]
                if osm_id not in addresses and (
                    addresses or osm_row[5] or osm_row[6] or osm_row[4] not in {"apartments", "residential"}
                ):
                    continue
            elif not buildings_at_point and len(nearby) == 1:
                osm_id = nearby[0]
            else:
                continue
        elif number in links and links[number] in addresses:
            osm_id = links[number]
        else:
            continue
        if number and (links.get(number, osm_id) != osm_id or numbers_by_osm.get(osm_id, number) != number):
            continue
        proposals[osm_id].append((number, row))
    return {osm_id: values[0] for osm_id, values in proposals.items() if len(values) == 1}


def address_points(path, buildings, city_ids):
    """Use a point address where it identifies exactly one building footprint."""
    if path is None:
        return {}
    with path.open(encoding="utf-8") as stream:
        response = json.load(stream)
    if response.get("remark") or not response.get("elements"):
        raise ValueError("Выгрузка адресных точек OSM пуста или выполнена частично")
    ids, polygons, tagged_addresses = [], [], {}
    for osm_id, _, _, _, _, street, house, _, _, flat in buildings:
        polygon = outline(flat)
        if not polygon.is_valid or polygon.is_empty:
            continue
        ids.append(osm_id)
        polygons.append(polygon)
        tagged_addresses[osm_id] = street, house
    tree = STRtree(polygons)
    proposals = defaultdict(dict)
    for node in response["elements"]:
        tags = node.get("tags", {})
        street = tags.get("addr:street") or tags.get("addr:place")
        house = tags.get("addr:housenumber")
        key = street_key(street), house_key(house)
        if not all(key) or not key[0][1] or node.get("type") != "node":
            continue
        point = Point(node["lon"] * METRES_X, node["lat"] * METRES_Y)
        hits = tree.query(point, predicate="covered_by")
        if len(hits) == 0 and tags.get("entrance"):
            hits = tree.query(point, predicate="dwithin", distance=0.30)
        if len(hits) != 1:
            continue
        osm_id = ids[hits[0]]
        if osm_id not in city_ids:
            continue
        tagged_street, tagged_house = tagged_addresses[osm_id]
        key = normalized_street(key[0]), key[1]
        tagged_street_key = street_key(tagged_street)
        if (tagged_street_key and normalized_street(tagged_street_key) != key[0]) or (
            tagged_house and house_key(tagged_house) != key[1]
        ):
            continue
        proposals[osm_id][key] = (street, house)
    return {osm_id: next(iter(choices.values())) for osm_id, choices in proposals.items() if len(choices) == 1}


GAR_EXTRACT = OSM.parent.parent / "gar" / "saratov_houses.json"


def gar_links(path, by_address, gko_addresses, by_cadastre, links, excluded, eligible):
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as stream:
        dataset = json.load(stream)
    houses = defaultdict(list)
    for row in dataset["houses"]:
        street, house = street_key(row["street"]), house_key(row["house"])
        if street and street[0] and house:
            houses[(normalized_street(street), house)].append(row)
    assigned = set(links.values())
    result = {}
    for key, rows in houses.items():
        footprints = by_address.get(key, ())
        if len(rows) != 1 or len(footprints) != 1:
            continue
        row, = rows
        osm_id, = footprints
        number = row.get("cad")
        if (not number or row["kind"] not in {"2", "5", "7"} or osm_id not in eligible
                or osm_id in assigned or number in links or number in excluded):
            continue
        if gko_addresses.get(key, set()) - {number}:
            continue
        gko = by_cadastre.get(number)
        if gko and gko["key"] and gko["key"] != key:
            continue
        links[number] = osm_id
        assigned.add(osm_id)
        result[osm_id] = (row, "ГАР ФНС " + dataset["version"] + ", однозначный адрес")
    return result


def match_records(records, housing, addresses_path=None):
    with SCORED_BUILDINGS.open("rb") as stream:
        map_ids = set(map(int, pickle.load(stream)["R"]["osm_id"]))
    with OSM.open(encoding="utf-8") as stream:
        buildings = json.load(stream)["rows"]
    tags = osm_attributes()
    previous, excluded = prior_registry()
    explicit_city = {osm_id for osm_id, (_, _, city) in tags.items() if city}
    point_addresses = address_points(addresses_path, buildings, map_ids | explicit_city)
    print(f"Контуров с адресом из адресной точки: {len(point_addresses):,}", flush=True)
    previous_ids = {row["cadastral_number"]: osm_id for osm_id, row in previous.items()}
    by_address, by_name = defaultdict(list), defaultdict(list)
    for row in buildings:
        osm_id, _, _, _, _, street, house, *_ = row
        if osm_id not in map_ids and osm_id not in explicit_city:
            continue
        street, house = point_addresses.get(osm_id, (street, house))
        street, house = street_key(street), house_key(house)
        if street and street[1] and house:
            street = normalized_street(street)
            by_address[(street, house)].append(osm_id)
            by_name[(street[1], house)].append((street[0], osm_id))
    by_cadastre = {}
    gko_addresses, gko_names = defaultdict(set), defaultdict(set)
    for row in records:
        number = text(row["cadastral_number"])
        by_cadastre[number] = row
        key = city_key(row["city_address"])
        row["key"] = key
        if key:
            street, house = key
            gko_addresses[key].add(number)
            gko_names[(street[1], house)].add(number)
    manual = {}
    if MANUAL_LINKS.is_file():
        osm_rows = {row[0]: row for row in buildings}
        with MANUAL_LINKS.open(encoding="utf-8") as stream:
            manual_records = json.load(stream)
        for entry in manual_records:
            osm_id, number = entry["osm_id"], entry["cadastral_number"]
            row, gko = osm_rows.get(osm_id), by_cadastre.get(number)
            key = city_key(entry["address"])
            if (not row or not gko or not key or key != gko["key"]
                    or osm_id not in by_address.get(city_key(entry.get("osm_address", entry["address"])), ())
                    or osm_id in previous or number in previous_ids):
                raise ValueError(f"Ручная привязка требует сверки: {osm_id} / {number}")
            manual[osm_id] = entry
            previous[osm_id] = entry
            previous_ids[number] = osm_id
    proposed, review = defaultdict(list), []
    for number, record in by_cadastre.items():
        if number in previous_ids:
            continue
        key = record["key"]
        if number in excluded:
            reason = "Спорное сопоставление при предыдущей сверке"
        elif not key:
            reason = "Адрес не удалось привести к улице и номеру дома"
        elif len(gko_addresses[key]) > 1:
            reason = "Несколько кадастровых зданий по адресу"
        else:
            candidates = by_address.get(key, [])
            street, house = key
            if not candidates and len(gko_names[(street[1], house)]) == 1:
                same_name = by_name.get((street[1], house), [])
                if len(same_name) == 1 and (street[0] is None or same_name[0][0] is None):
                    candidates = [same_name[0][1]]
            if len(candidates) == 1 and candidates[0] not in previous:
                proposed[candidates[0]].append(number)
                continue
            reason = "Нет контура с этим адресом" if not candidates else "Несколько объектов претендуют на контур"
        review.append((number, record["city_address"], reason))
    links = dict(previous_ids)
    for osm_id, numbers in proposed.items():
        if len(numbers) == 1:
            links[numbers[0]] = osm_id
        else:
            review.extend((n, by_cadastre[n]["city_address"], "Несколько записей на контур") for n in numbers)
    city_ids = map_ids | set(links.values()) | explicit_city
    gis = match_housing(housing, buildings, city_ids, by_address, links, excluded)
    housing_by_number = defaultdict(list)
    for row in housing:
        housing_by_number[text(row["cadastral_number"])].append(row)
    for osm_id, entry in manual.items():
        number = entry["cadastral_number"]
        candidates = housing_by_number[number]
        if len(candidates) == 1 and candidates[0]["key"] == city_key(entry["address"]):
            gis[osm_id] = (number, candidates[0])
    gis_numbers = Counter(number for number, _ in gis.values() if number)
    for osm_id, (number, _) in gis.items():
        if number and gis_numbers[number] == 1:
            links[number] = osm_id
    gar = gar_links(GAR_EXTRACT, by_address, gko_addresses, by_cadastre, links, excluded, map_ids | set(gis))
    numbers_by_osm = {osm_id: number for number, osm_id in links.items()}
    review = [reason for reason in review if reason[0] not in links]
    result = []
    for osm_id, _, _, footprint, osm_type, street, house, osm_name, *_ in buildings:
        if osm_id not in map_ids and osm_id not in numbers_by_osm and osm_id not in gis:
            continue
        number = numbers_by_osm.get(osm_id)
        record = by_cadastre.get(number)
        original = previous.get(osm_id, {})
        category, label = gko_category(record) if record else (None, None)
        housing_number, housing_row = gis.get(osm_id, (None, None))
        if housing_row and gis_numbers[housing_number] <= 1:
            category, label = category or "residential", label or "Многоквартирный дом"
        else:
            housing_row = {}
        osm_year, osm_levels, _ = tags.get(osm_id, (None, None, False))
        gko_year, opened = (year(record["year_built"]), year(record["year_opened"])) if record else (None, None)
        if not record and original:
            gko_year = year(original.get("year_built"))
        gko_area = numeric_area(record["area_m2"]) if record else numeric_area(original.get("area_m2"))
        gko_floors = (record["floors"] if record else None) or original.get("floors")
        sgu_area = campus_area(osm_id, street, house, osm_name)
        point_address = " ".join(point_addresses[osm_id]) if osm_id in point_addresses and (not street or not house) else None
        gar_house, gar_method = gar.get(osm_id, ({}, None))
        result.append((
            osm_id, number, original.get("address") or gar_house.get("address") or (record["city_address"] if record else housing_row.get("city_address", "")),
            " ".join(filter(None, (street, house))), osm_name, osm_type, footprint,
            gko_area, gko_year, opened, osm_year, gko_floors, osm_levels,
            text(record["purpose"]) if record else "", original.get("category_gko") or category,
            original.get("type_detail") or label, record["source_row"] if record else None,
            gar_method if gar_method else "ручная сверка" if osm_id in manual else "проверка адреса и координат" if original else "ГИС ЖКХ: адрес и координаты"
            if housing_row else "однозначный адрес" if number else None,
            numeric_area(housing_row.get("total_area")), year(housing_row.get("building_year")),
            housing_row.get("gisgkh_guid"),
            sgu_area, SGU_SOURCE if sgu_area else None, point_address,
            original.get("wall_material"), original.get("underground_floors"), original.get("source"), gar_house.get("guid"),
        ))
    return result, review


def write_registry(destination, rows, review):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=destination.parent, suffix=".sqlite", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        db = sqlite3.connect(temporary)
        try:
            with db:
                db.executescript("""
                    CREATE TABLE buildings (
                        osm_id INTEGER PRIMARY KEY, cadastral_number TEXT UNIQUE,
                        address TEXT, osm_address TEXT, osm_name TEXT, osm_type TEXT, footprint_m2 REAL,
                        area_m2 REAL, year_built INTEGER, year_opened INTEGER, osm_start_year INTEGER,
                        floors TEXT, osm_levels TEXT, purpose TEXT, category_gko TEXT, type_detail TEXT,
                        gko_source_row INTEGER, match_method TEXT,
                        gis_area_m2 REAL, gis_year_built INTEGER, gisgkh_guid TEXT,
                        institution_area_m2 REAL, institution_source TEXT, osm_point_address TEXT,
                        wall_material TEXT, underground_floors INTEGER, manual_source TEXT, gar_guid TEXT
                    );
                    CREATE TABLE manual_review (cadastral_number TEXT PRIMARY KEY, address TEXT, reason TEXT);
                """)
                db.executemany("INSERT INTO buildings VALUES (" + ",".join("?" for _ in rows[0]) + ")", rows)
                db.executemany("INSERT INTO manual_review VALUES (?,?,?)", review)
        finally:
            db.close()
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("extract", type=Path)
    parser.add_argument("--output", type=Path, default=CITY_DATABASE)
    parser.add_argument("--extract-only", action="store_true")
    parser.add_argument("--housing", type=Path, help="Опубликованный архив Parquet ГИС ЖКХ")
    parser.add_argument("--osm-addresses", type=Path, help="JSON адресных точек OpenStreetMap")
    args = parser.parse_args()
    if not args.extract.exists():
        extract(args.workbook, args.extract)
    if args.extract_only:
        return
    with args.extract.open(encoding="utf-8") as stream:
        records = json.load(stream)
    housing = housing_records(args.housing)
    rows, review = match_records(records, housing, args.osm_addresses)
    write_registry(args.output, rows, review)
    print(f"Контуров на карте: {len(rows):,}; привязано ГКО: {sum(row[16] is not None for row in rows):,}; "
          f"привязано ГИС ЖКХ: {sum(bool(row[20]) for row in rows):,} из {len(housing):,}; "
          f"на ручную сверку ГКО: {len(review):,}", flush=True)


if __name__ == "__main__":
    main()
