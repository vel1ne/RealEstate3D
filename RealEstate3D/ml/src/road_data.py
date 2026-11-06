"""Загрузка дорожных данных, подготовленных дата-инженером (папка data_engineering).

Данные не копируются в ml: читаются напрямую из data_engineering/data/processed,
чтобы у всей команды был один источник и обновления DE сразу попадали в модель.

Пример:
    from src.road_data import load_roads, load_points
    roads = load_roads()             # pandas.DataFrame, 1 строка = 1 OSM-линия
    roads_gdf = load_roads(geo=True) # geopandas.GeoDataFrame (если установлен geopandas)
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DE_PROCESSED = REPO / "data_engineering" / "data" / "processed"
SQLITE_PATH = DE_PROCESSED / "saratov_roads.sqlite"


def _connect() -> sqlite3.Connection:
    if not SQLITE_PATH.is_file():
        raise FileNotFoundError(
            f"Нет {SQLITE_PATH}. Соберите данные DE: в папке data_engineering выполните "
            "`python scripts/fetch_osm.py` и `python scripts/build_data.py`."
        )
    return sqlite3.connect(SQLITE_PATH)


def _to_geo(df: pd.DataFrame):
    import geopandas as gpd
    from shapely.geometry import shape

    geom = df.pop("geometry_geojson").map(lambda s: shape(json.loads(s)))
    return gpd.GeoDataFrame(df, geometry=geom, crs="EPSG:4326")


def load_roads(geo: bool = False):
    """Участки дорог (таблица road_segment): класс дороги, ограничения массы/габаритов, длина.

    NULL в ограничениях = «нет данных», а НЕ «ограничения нет» (см. ПЕРЕДАЧА_КОМАНДЕ.md).
    """
    with _connect() as con:
        df = pd.read_sql("SELECT * FROM road_segment", con)
    return _to_geo(df) if geo else df


def load_points(geo: bool = False):
    """Точечные препятствия и ограничения (шлагбаумы, maxheight, maxweight)."""
    with _connect() as con:
        df = pd.read_sql("SELECT * FROM point_constraint", con)
    return _to_geo(df) if geo else df


def load_turn_restrictions() -> pd.DataFrame:
    """Сырые отношения запретов поворота."""
    with _connect() as con:
        return pd.read_sql("SELECT * FROM turn_restriction_raw", con)


def dataset_info() -> dict:
    """Дата и происхождение снимка OSM — сохраняйте вместе с обученной моделью."""
    with _connect() as con:
        con.row_factory = sqlite3.Row
        return dict(con.execute("SELECT * FROM dataset").fetchone())
