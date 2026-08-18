from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

SOURCE=Path(os.environ.get('EREDIVISIE_ARCHIVE_SOURCE','archive-source/data/2025'))
OUT=Path(os.environ.get('NEXUS_EREDIVISIE_ARCHIVE_OUT','/mnt/data/nexus-eredivisie-archive-2025-v1'))
ARCHIVE_SHA=os.environ.get('EREDIVISIE_ARCHIVE_SHA','UNKNOWN')


def now(): return datetime.now(timezone.utc).isoformat()
def mkdir(p): p.mkdir(parents=True,exist_ok=True); return p
def sha_file(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def dump(p,o): mkdir(p.parent);p.write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def write_csv(p,rows):
    mkdir(p.parent)
    if not rows:p.write_text('',encoding='utf-8');return
    fs=[];seen=set()
    for r in rows:
        for k in r:
            if k not in seen:seen.add(k);fs.append(k)
    with p.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fs);w.writeheader();w.writerows(rows)

def main():
    if not SOURCE.is_dir(): raise RuntimeError(f'missing archive source {SOURCE}')
    if OUT.exists():shutil.rmtree(OUT)
    raw=OUT/'raw'/'TopMarx-eredivisie-data-2025'
    mkdir(raw.parent);shutil.copytree(SOURCE,raw)
    bootstrap=raw/'eredivisie-bootstrap_2025.json'
    if not bootstrap.is_file():raise RuntimeError('missing archived bootstrap')
    obj=json.load(open(bootstrap,encoding='utf-8'))
    elements=obj.get('elements') or [] if isinstance(obj,dict) else []
    teams=obj.get('teams') or [] if isinstance(obj,dict) else []
    tmap={t.get('id'):t for t in teams if isinstance(t,dict)}
    rows=[]
    for e in elements:
        if not isinstance(e,dict):continue
        t=tmap.get(e.get('team')) or {}
        rows.append({
            'provider':'ESPN_FANTASY_VOETBAL_ARCHIVE',
            'competition':'Eredivisie',
            'season':'2025-26',
            'provider_player_id':e.get('id'),
            'player_code':e.get('code'),
            'first_name':e.get('first_name'),
            'second_name':e.get('second_name'),
            'web_name':e.get('web_name'),
            'team_id':e.get('team'),
            'team_name':t.get('name'),
            'element_type':e.get('element_type'),
            'minutes':e.get('minutes'),
            'starts':e.get('starts'),
            'goals_scored':e.get('goals_scored'),
            'assists':e.get('assists'),
            'own_goals':e.get('own_goals'),
            'penalties_missed':e.get('penalties_missed'),
            'penalties_saved':e.get('penalties_saved'),
            'yellow_cards':e.get('yellow_cards'),
            'red_cards':e.get('red_cards'),
            'clean_sheets':e.get('clean_sheets'),
            'goals_conceded':e.get('goals_conceded'),
            'saves':e.get('saves'),
            'total_points':e.get('total_points'),
            'provider_fields_json':json.dumps(e,ensure_ascii=False,default=str,separators=(',',':')),
        })
    write_csv(OUT/'normalized'/'player-season-index.csv',rows)
    player_files=list((raw/'players').rglob('*')) if (raw/'players').is_dir() else []
    player_files=[p for p in player_files if p.is_file()]
    gameweek_files=list((raw/'gameweeks').rglob('*')) if (raw/'gameweeks').is_dir() else []
    gameweek_files=[p for p in gameweek_files if p.is_file()]
    csv_files=list((raw/'csv').rglob('*')) if (raw/'csv').is_dir() else []
    csv_files=[p for p in csv_files if p.is_file()]
    inventory=[]
    for p in sorted(x for x in OUT.rglob('*') if x.is_file()):
        if p.name=='file-inventory.json':continue
        inventory.append({'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':sha_file(p)})
    dump(OUT/'file-inventory.json',inventory)
    manifest={
        'schema':'NEXUS_EREDIVISIE_ARCHIVE_2025_V1',
        'status':'PASS' if len(elements)>300 and len(player_files)>100 and len(gameweek_files)>10 else 'FAIL_VALIDATION',
        'capture_completed':now(),
        'archive_repository':'TopMarx/eredivisie',
        'archive_git_sha':ARCHIVE_SHA,
        'archive_path':'data/2025',
        'season':'2025-26',
        'coverage':{
            'bootstrap_players':len(elements),
            'teams':len(teams),
            'player_files':len(player_files),
            'gameweek_files':len(gameweek_files),
            'csv_files':len(csv_files),
            'total_files':len(inventory),
        },
        'governance':{
            'current_2026_27_snapshot_overwritten':False,
            'cross_provider_normalization_performed':False,
            'missing_values_filled':False,
            'predictive_models_modified':False,
            'decision_layer_started':False,
        },
    }
    dump(OUT/'manifest.json',manifest)
    print(json.dumps({'status':manifest['status'],'coverage':manifest['coverage'],'archive_git_sha':ARCHIVE_SHA},indent=2))

if __name__=='__main__':main()
