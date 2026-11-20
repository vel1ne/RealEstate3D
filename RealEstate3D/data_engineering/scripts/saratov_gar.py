"""Extract current Saratov street addresses from the region 64 GAR XML files."""
import argparse
from collections import Counter, defaultdict
from datetime import date
import gzip
import json
from pathlib import Path
import re
from xml.etree import ElementTree


def elements(directory, name):
    with gzip.open(directory / (name + ".xml.gz"), "rb") as stream:
        events = ElementTree.iterparse(stream, events=("start", "end"))
        _, root = next(events)
        for event, elem in events:
            if event == "end" and elem is not root:
                yield elem.attrib
                root.clear()


def extract(directory):
    version = date.fromisoformat(directory.name).isoformat()
    objects = {a["OBJECTID"]: a for a in elements(directory, "AS_ADDR_OBJ")
               if a["ISACTIVE"] == a["ISACTUAL"] == "1"}
    city, = [i for i, a in objects.items() if a["LEVEL"] == "5" and a["NAME"] == "Саратов"]
    streets = {}
    parents = {}
    for a in elements(directory, "AS_ADM_HIERARCHY"):
        if a["ISACTIVE"] != "1" or city not in a["PATH"].split("."):
            continue
        i, parent = a["OBJECTID"], a.get("PARENTOBJID")
        if parent == city and i in objects and objects[i]["LEVEL"] == "8":
            street = objects[i]
            streets[i] = street["TYPENAME"] + " " + street["NAME"]
        parents[i] = parent
    types = {a["ID"]: a["SHORTNAME"] for a in elements(directory, "AS_HOUSE_TYPES")}
    extras = {a["ID"]: a["SHORTNAME"] for a in elements(directory, "AS_ADDHOUSE_TYPES")}
    houses = {}
    for a in elements(directory, "AS_HOUSES"):
        street = streets.get(parents.get(a["OBJECTID"]))
        if not street or a["ISACTIVE"] != "1" or a["ISACTUAL"] != "1" or not a.get("HOUSENUM"):
            continue
        number = a["HOUSENUM"]
        for n in ("1", "2"):
            if a.get("ADDNUM" + n):
                number += " " + extras[a["ADDTYPE" + n]] + " " + a["ADDNUM" + n]
        kind = a.get("HOUSETYPE")
        houses[a["OBJECTID"]] = dict(street=street, house=number, kind=kind,
                                      address=f"Саратов, {street}, {types.get(kind, '')} {number}",
                                      guid=a["OBJECTGUID"])
    params = {a["CODE"]: a["ID"] for a in elements(directory, "AS_PARAM_TYPES")}
    cad_type, retired_type = params["CadastrNum"], params["DateOfRemovalFromCadastrReg"]
    numbers, retired = defaultdict(set), set()
    for a in elements(directory, "AS_HOUSES_PARAMS"):
        i = a["OBJECTID"]
        if i not in houses or not (a["STARTDATE"] <= version < a["ENDDATE"]):
            continue
        if a["TYPEID"] == cad_type:
            numbers[i].add(a["VALUE"].strip())
        elif a["TYPEID"] == retired_type and a.get("VALUE", "").strip():
            retired.add(i)
    frequency = Counter(n for values in numbers.values() for n in values)
    for i, candidates in numbers.items():
        if len(candidates) == 1 and i not in retired:
            number, = candidates
            if frequency[number] == 1 and re.fullmatch(r"64:\d+:\d+:\d+", number):
                houses[i]["cad"] = number
    return {"version": version, "houses": list(houses.values())}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = extract(args.directory)
    temporary = args.output.with_suffix(".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    temporary.replace(args.output)
    print("Адресов ГАР:", len(result["houses"]), "с уникальным номером:", sum("cad" in h for h in result["houses"]))
