"""Fetch a fresh OSM snapshot. Backs up existing raw file; public Overpass only.
Run explicitly when an update is needed, then run build_data.py.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[1]
query=(ROOT/'data/raw/query.overpassql').read_text(encoding='utf-8')
destination=ROOT/'data/raw/saratov_osm.json'
payload=None
for endpoint in ['https://overpass-api.de/api/interpreter','https://overpass.kumi.systems/api/interpreter']:
    try:
        request=Request(endpoint,data=urlencode({'data':query}).encode(),
                        headers={'User-Agent':'RealEstate3D-Saratov-research/0.1'})
        with urlopen(request,timeout=220) as response:
            candidate=response.read()
        parsed=json.loads(candidate)
        if parsed.get('remark') or not parsed.get('elements'):
            raise RuntimeError(parsed.get('remark','No elements'))
        payload=candidate
        break
    except Exception as exc:
        print(endpoint,exc,flush=True)
if payload is None:
    raise RuntimeError('No complete snapshot retrieved. Existing data is unchanged.')
if destination.exists():
    backup=ROOT/'data/backups'
    backup.mkdir(exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    (backup/('saratov_osm_'+stamp+'.json')).write_bytes(destination.read_bytes())
temporary=destination.with_suffix('.partial')
temporary.write_bytes(payload)
temporary.replace(destination)
print('Saved snapshot. Run: python scripts/build_data.py')
