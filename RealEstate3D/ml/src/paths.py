"""Пути проекта. Все расчёты ML живут в папке ml/, дороги берутся у дата-инженера (только чтение)."""
import os
from pathlib import Path

ML = Path(__file__).resolve().parents[1]
REPO = ML.parent

# база дорог дата-инженера (data_engineering) — читаем, не меняем
DE_SQLITE = Path(os.environ.get("WAREHOUSE_ROADS_SQLITE",
                                REPO / "data_engineering" / "data" / "processed" / "saratov_roads.sqlite"))

CONFIG = ML / "config" / "warehouse_config.json"
DATA = ML / "data"            # промежуточные данные (в git не попадают)
OSM = DATA / "osm"            # здания, промзоны, ж/д, школы… из OpenStreetMap
MODELS = ML / "models"        # обученные модели (в git не попадают)
OUT = ML / "out"              # карта, Excel, отчёты (в git не попадают)

for p in (DATA, OSM, MODELS, OUT):
    p.mkdir(parents=True, exist_ok=True)
