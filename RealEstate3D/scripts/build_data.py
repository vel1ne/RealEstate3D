"""Rebuild local SQLite, GeoJSON, PostGIS import and offline map from raw OSM.
Python 3.10+, standard library only. Run from any directory.
"""
import collections
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/saratov_osm.json'
raw_bytes = RAW.read_bytes()
raw = json.loads(raw_bytes)
if raw.get('remark'):
    raise RuntimeError('Incomplete Overpass response: '+raw['remark'])
retrieved = dt.datetime.fromtimestamp(RAW.stat().st_mtime, dt.timezone.utc).isoformat()
base = raw['osm3s']['timestamp_osm_base']
dataset_key = 'saratov_osm_'+hashlib.sha256(raw_bytes).hexdigest()[:12]
box = [45.70, 51.35, 46.35, 51.82]  # GeoJSON: west,south,east,north.
fields = ['osm_way_id','name','ref','highway','access','vehicle','motor_vehicle','hgv','goods',
          'hgv_articulated','oneway','surface','maxweight_t','maxweightrating_t','maxaxleload_t',
          'maxheight_m','maxwidth_m','maxlength_m','osm_version','osm_modified_at']
metrics = [('maxweight_t','maxweight'),('maxweightrating_t','maxweightrating'),
           ('maxaxleload_t','maxaxleload'),('maxheight_m','maxheight'),
           ('maxwidth_m','maxwidth'),('maxlength_m','maxlength')]

def metric(value):
    # Conservative: only a plain positive number in default OSM units.
    # Other units, "none", "unsigned", expressions remain in raw tags for review.
    if value is None or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',value):
        return None
    val = float(value)
    return val if val>0 else None

def length_m(coords):
    total = 0.0
    for a,b in zip(coords,coords[1:]):
        lon1,lat1,lon2,lat2=map(math.radians,(*a,*b))
        h=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
        total += 6371008.8*2*math.asin(min(1,math.sqrt(h)))
    return total

roads=[]; points=[]; turns=[]; rejected=[]
for el in raw['elements']:
    t=el.get('tags',{})
    if el['type']=='way':
        geometry=el.get('geometry',[])
        if len(geometry)<2 or any('lon' not in p or 'lat' not in p for p in geometry):
            rejected.append(el['id']); continue
        coords=[[p['lon'],p['lat']] for p in geometry]
        row={k:t.get(k) for k in fields}
        row.update(osm_way_id=el['id'], osm_version=el.get('version'), osm_modified_at=el.get('timestamp'))
        for col,key in metrics: row[col]=metric(t.get(key))
        row['tags']=t; row['nodes']=el.get('nodes',[]); row['geometry']={'type':'LineString','coordinates':coords}
        row['length_m']=round(length_m(coords),1)
        roads.append(row)
    elif el['type']=='node':
        points.append({'type':'Feature','id':el['id'],'properties':{'osm_node_id':el['id'],'tags':t},
                       'geometry':{'type':'Point','coordinates':[el['lon'],el['lat']]}})
    elif el['type']=='relation' and t.get('type')=='restriction':
        turns.append(el)
if not roads: raise RuntimeError('No roads')
assert len({r['osm_way_id'] for r in roads})==len(roads)

def dumps(x): return json.dumps(x,ensure_ascii=False,separators=(',',':'))
features=[{'type':'Feature','id':r['osm_way_id'], 'properties':{k:v for k,v in r.items() if k not in ('geometry','nodes')},'geometry':r['geometry']} for r in roads]
collection={'type':'FeatureCollection','bbox':box,'features':features}
(ROOT/'data/processed/roads.geojson').write_text(dumps(collection),encoding='utf-8')
(ROOT/'data/processed/point_constraints.geojson').write_text(dumps({'type':'FeatureCollection','features':points}),encoding='utf-8')
(ROOT/'data/processed/turn_restrictions.json').write_text(dumps(turns),encoding='utf-8')
counter=collections.Counter(r['highway'] for r in roads)
stats={'project_date':'2026-10-27','dataset_key':dataset_key,'retrieved_at':retrieved,'osm_base_at':base,
 'bbox_wsen':box,'sha256':hashlib.sha256(raw_bytes).hexdigest(),
 'road_ways':len(roads),'point_constraints':len(points),'turn_relations':len(turns),
 'rejected_ways':rejected,'approx_way_length_km':round(sum(r['length_m'] for r in roads)/1000,1),
 'highway_counts':dict(counter),'with_hgv_tag':sum(r['hgv'] is not None for r in roads),
 'with_maxweight_numeric':sum(r['maxweight_t'] is not None for r in roads),
 'with_maxheight_numeric':sum(r['maxheight_m'] is not None for r in roads),
 'with_any_conditional_tag':sum(any(':conditional' in k for k in r['tags']) for r in roads),
 'hgv_values':dict(collections.Counter(r['hgv'] for r in roads if r['hgv']))}
(ROOT/'data/processed/quality_report.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2),encoding='utf-8')

# SQLite is a ready-to-open local preview; PostGIS schema is the application target.
db=sqlite3.connect(ROOT/'data/processed/saratov_roads.sqlite')
db.execute('PRAGMA foreign_keys=ON')
db.executescript('''
CREATE TABLE IF NOT EXISTS dataset(dataset_key TEXT PRIMARY KEY,retrieved_at TEXT,osm_base_at TEXT,bbox_json TEXT,sha256 TEXT);
CREATE TABLE IF NOT EXISTS road_segment(
osm_way_id INTEGER PRIMARY KEY,name TEXT,ref TEXT,highway TEXT,access TEXT,vehicle TEXT,motor_vehicle TEXT,hgv TEXT,goods TEXT,
hgv_articulated TEXT,oneway TEXT,surface TEXT,maxweight_t REAL,maxweightrating_t REAL,maxaxleload_t REAL,
maxheight_m REAL,maxwidth_m REAL,maxlength_m REAL,osm_version INTEGER,osm_modified_at TEXT,
tags_json TEXT NOT NULL,node_ids_json TEXT NOT NULL,geometry_geojson TEXT NOT NULL,length_m REAL NOT NULL,
dataset_key TEXT NOT NULL REFERENCES dataset(dataset_key));
CREATE INDEX IF NOT EXISTS road_ref_idx ON road_segment(ref);
CREATE INDEX IF NOT EXISTS road_name_idx ON road_segment(name);
CREATE TABLE IF NOT EXISTS point_constraint(osm_node_id INTEGER PRIMARY KEY,tags_json TEXT,geometry_geojson TEXT,dataset_key TEXT REFERENCES dataset);
CREATE TABLE IF NOT EXISTS turn_restriction_raw(osm_relation_id INTEGER PRIMARY KEY,tags_json TEXT,members_json TEXT,dataset_key TEXT REFERENCES dataset);
''')
with db:
    # Replace the generated preview snapshot; source raw data is retained.
    for table in ['road_segment','point_constraint','turn_restriction_raw','dataset']: db.execute('DELETE FROM '+table)
    db.execute('INSERT INTO dataset VALUES(?,?,?,?,?)',(dataset_key,retrieved,base,dumps(box),stats['sha256']))
    columns=fields+['tags_json','node_ids_json','geometry_geojson','length_m','dataset_key']
    db.executemany('INSERT INTO road_segment('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',
      [tuple(r[k] for k in fields)+(dumps(r['tags']),dumps(r['nodes']),dumps(r['geometry']),r['length_m'],dataset_key) for r in roads])
    db.executemany('INSERT INTO point_constraint VALUES(?,?,?,?)',[(p['id'],dumps(p['properties']['tags']),dumps(p['geometry']),dataset_key) for p in points])
    db.executemany('INSERT INTO turn_restriction_raw VALUES(?,?,?,?)',[(x['id'],dumps(x['tags']),dumps(x['members']),dataset_key) for x in turns])
assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert db.execute('SELECT COUNT(*) FROM road_segment').fetchone()[0]==len(roads)
assert not db.execute('PRAGMA foreign_key_check').fetchall()
db.close()

def quote(x):
    if x is None: return 'NULL'
    if isinstance(x,(int,float)): return str(x)
    return "'"+str(x).replace("'","''")+"'"

with (ROOT/'sql/02_import_roads_postgis.sql').open('w',encoding='utf-8') as f:
    f.write("BEGIN;\nSET standard_conforming_strings=on;\nSET search_path TO logistics,public;\n")
    f.write("INSERT INTO data_source VALUES('osm','OpenStreetMap','https://www.openstreetmap.org/copyright','ODbL 1.0','Community observations; not an official truck permit') ON CONFLICT(source_key) DO NOTHING;\n")
    vals=[dataset_key,'osm',retrieved,base,dumps(box),(ROOT/'data/raw/query.overpassql').read_text(encoding='utf-8'),stats['sha256']]
    f.write('INSERT INTO dataset VALUES('+','.join(map(quote,vals))+') ON CONFLICT(dataset_key) DO NOTHING;\n')
    f.write('UPDATE road_segment SET is_current=false;\n')
    for r in roads:
        cols=fields+['dataset_key','tags','node_ids','geom','is_current']
        vals=[quote(r[k]) for k in fields]+[quote(dataset_key),quote(dumps(r['tags']))+'::jsonb',quote(dumps(r['nodes']))+'::jsonb',
           'ST_SetSRID(ST_GeomFromGeoJSON('+quote(dumps(r['geometry']))+'),4326)','true']
        update=','.join(k+'=EXCLUDED.'+k for k in cols if k!='osm_way_id')
        f.write('INSERT INTO road_segment('+','.join(cols)+') VALUES('+','.join(vals)+') ON CONFLICT(osm_way_id) DO UPDATE SET '+update+';\n')
    # These are raw snapshot caches, unlike the manually maintained restriction table.
    f.write('DELETE FROM point_constraint;\nDELETE FROM turn_restriction_raw;\n')
    for p in points:
        f.write('INSERT INTO point_constraint VALUES('+','.join([quote(p['id']),quote(dataset_key),quote(dumps(p['properties']['tags']))+'::jsonb',
          'ST_SetSRID(ST_GeomFromGeoJSON('+quote(dumps(p['geometry']))+'),4326)'])+');\n')
    for t in turns:
        f.write('INSERT INTO turn_restriction_raw VALUES('+','.join([quote(t['id']),quote(dataset_key),quote(dumps(t['tags']))+'::jsonb',quote(dumps(t['members']))+'::jsonb'])+');\n')
    f.write('COMMIT;\nANALYZE road_segment;\n')

template=(ROOT/'scripts/map_template.html').read_text(encoding='utf-8')
# Escape HTML-significant bytes to keep OSM text data out of script syntax.
def script_json(x): return dumps(x).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026')
page=template.replace('__ROADS_JSON__',script_json(collection)).replace('__POINTS_JSON__',script_json(points)).replace('__STATS_JSON__',script_json(stats))
(ROOT/'maps/saratov_trucks.html').write_text(page,encoding='utf-8')
print(json.dumps(stats,ensure_ascii=False,indent=2))
