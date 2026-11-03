"""Refresh only the HTML map from existing processed data (no database changes)."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def data(path):
    return json.loads((ROOT/path).read_text(encoding='utf-8'))
def script_json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
template=(ROOT/'scripts/map_template.html').read_text(encoding='utf-8')
page=template.replace('__ROADS_JSON__',script_json(data('data/processed/roads.geojson')))
page=page.replace('__POINTS_JSON__',script_json(data('data/processed/point_constraints.geojson')['features']))
page=page.replace('__STATS_JSON__',script_json(data('data/processed/quality_report.json')))
(ROOT/'maps/saratov_trucks.html').write_text(page,encoding='utf-8')
print('Map updated from existing data.')
