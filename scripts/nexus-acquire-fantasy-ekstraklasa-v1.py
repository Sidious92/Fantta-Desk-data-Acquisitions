from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

OUT=Path(os.environ.get('NEXUS_EKSTRAKLASA_OUT','/mnt/data/nexus-fantasy-ekstraklasa-v1'))
BASE='https://fantasy.ekstraklasa.org'
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept-Language':'pl,en;q=0.8','X-Requested-With':'XMLHttpRequest'}
ID_PATTERNS=[re.compile(r'stats-player/(\d+)'),re.compile(r'Player\.(?:info|show|open)\((\d+)\)'),re.compile(r'player[^0-9]{0,20}(\d+)',re.I)]

def now(): return datetime.now(timezone.utc).isoformat()
def mkdir(p): p.mkdir(parents=True,exist_ok=True); return p
def sha(b): return hashlib.sha256(b).hexdigest()
def dump(p,o): mkdir(p.parent); p.write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def get(path,params=None):
    u=path if path.startswith('http') else urljoin(BASE+'/',path.lstrip('/'))
    r=requests.get(u,params=params or {},headers=HEADERS,timeout=35,allow_redirects=True)
    return r
def write_csv(p,rows):
    mkdir(p.parent)
    if not rows: p.write_text('',encoding='utf-8'); return
    fields=[]; seen=set()
    for r in rows:
        for k in r:
            if k not in seen: seen.add(k); fields.append(k)
    with p.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
def extract_id(row):
    if isinstance(row,dict):
        for key in ['id','playerId','player_id','playerID','idPlayer','id_player']:
            v=row.get(key)
            if isinstance(v,int) or (isinstance(v,str) and v.isdigit()): return int(v)
        text=json.dumps(row,ensure_ascii=False,default=str)
        for pat in ID_PATTERNS:
            m=pat.search(text)
            if m: return int(m.group(1))
    return None

def main():
    if OUT.exists(): shutil.rmtree(OUT)
    raw=mkdir(OUT/'raw'); norm=mkdir(OUT/'normalized'); started=now()
    page=get('/stats'); page.raise_for_status(); (raw/'stats-page.html').write_bytes(page.content)
    soup=BeautifulSoup(page.content,'lxml')
    rounds=[]
    sel=soup.select_one('#stats-round')
    if sel:
        for o in sel.find_all('option'):
            v=(o.get('value') or '').strip(); txt=' '.join(o.stripped_strings)
            if v and v not in {'0','all','-1'}: rounds.append({'value':v,'label':txt})
    # De-duplicate while preserving order.
    seen=set(); rounds=[x for x in rounds if not (x['value'] in seen or seen.add(x['value']))]
    match_ids=[]
    for a in soup.find_all('a',href=True):
        m=re.search(r'/stats-game/(\d+)',a.get('href') or '')
        if m and int(m.group(1)) not in match_ids: match_ids.append(int(m.group(1)))

    snapshots=[]; rows_flat=[]; player_ids=set(); field_inventory=set()
    scopes=[{'scope':'SEASON_TOTAL','round':''}]+[{'scope':f"ROUND_{x['value']}",'round':x['value'],'round_label':x['label']} for x in rounds]
    for scope in scopes:
        params={'round':scope['round'],'team':'','pos':'','played':0}
        r=get('/stats-list',params); rec={'scope':scope['scope'],'round':scope['round'],'round_label':scope.get('round_label'),'status':r.status_code,'url':r.url,'bytes':len(r.content),'sha256':sha(r.content)}
        path=raw/f"stats-list-{scope['scope'].lower()}.json"
        path.write_bytes(r.content); rec['local_path']=str(path.relative_to(OUT))
        try: obj=r.json()
        except Exception as exc:
            rec['error']=f'NON_JSON:{exc}'; snapshots.append(rec); continue
        data=obj if isinstance(obj,list) else (obj.get('data') if isinstance(obj,dict) else None)
        if not isinstance(data,list):
            rec['error']='JSON_NOT_LIST'; rec['json_type']=type(obj).__name__; snapshots.append(rec); continue
        rec['rows']=len(data); snapshots.append(rec)
        for row in data:
            if not isinstance(row,dict): continue
            field_inventory.update(row.keys()); pid=extract_id(row)
            if pid is not None: player_ids.add(pid)
            rows_flat.append({'provider':'LOTTO_FANTASY_EKSTRAKLASA','competition':'Ekstraklasa','scope':scope['scope'],'round':scope['round'] or None,'round_label':scope.get('round_label'),'provider_player_id':pid,'source_url':r.url,'source_sha256':sha(r.content),'provider_fields_json':json.dumps(row,ensure_ascii=False,default=str,separators=(',',':')),**row})
    dump(OUT/'stats-list-manifest.json',snapshots)
    write_csv(norm/'player-stats-by-scope.csv',rows_flat)

    detail_rows=[]; detail_errors=[]; detail_root=mkdir(raw/'player-details')
    def fetch_detail(pid):
        try:
            r=get(f'/stats-player/{pid}')
            p=detail_root/f'{pid}.bin'; p.write_bytes(r.content)
            return {'provider_player_id':pid,'status':r.status_code,'url':r.url,'content_type':r.headers.get('content-type'),'bytes':len(r.content),'sha256':sha(r.content),'source_local_path':str(p.relative_to(OUT)),'body_preview':r.text[:1000]}
        except Exception as exc: return {'provider_player_id':pid,'error':str(exc)}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs=[ex.submit(fetch_detail,pid) for pid in sorted(player_ids)]
        for fut in as_completed(futs):
            x=fut.result(); (detail_errors if x.get('error') else detail_rows).append(x)
    write_csv(norm/'player-detail-index.csv',detail_rows); dump(OUT/'player-detail-errors.json',detail_errors)

    match_rows=[]; match_errors=[]; match_root=mkdir(raw/'match-reports')
    def fetch_match(mid):
        try:
            r=get(f'/stats-game/{mid}'); p=match_root/f'{mid}.html'; p.write_bytes(r.content)
            return {'match_id':mid,'status':r.status_code,'url':r.url,'bytes':len(r.content),'sha256':sha(r.content),'source_local_path':str(p.relative_to(OUT))}
        except Exception as exc: return {'match_id':mid,'error':str(exc)}
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs=[ex.submit(fetch_match,mid) for mid in match_ids]
        for fut in as_completed(futs):
            x=fut.result(); (match_errors if x.get('error') else match_rows).append(x)
    write_csv(norm/'match-report-index.csv',match_rows); dump(OUT/'match-report-errors.json',match_errors)

    season_total=next((x for x in snapshots if x['scope']=='SEASON_TOTAL'),{})
    manifest={'schema':'NEXUS_FANTASY_EKSTRAKLASA_V1','status':'PASS' if int(season_total.get('rows',0) or 0)>100 else 'FAIL_VALIDATION','capture_started':started,'capture_completed':now(),'stats_page':{'url':page.url,'status':page.status_code,'sha256':sha(page.content)},'coverage':{'rounds_discovered':len(rounds),'snapshots':len(snapshots),'season_total_rows':season_total.get('rows',0),'flattened_scope_rows':len(rows_flat),'unique_player_ids_discovered':len(player_ids),'player_details_ok':len(detail_rows),'player_detail_errors':len(detail_errors),'public_match_reports_discovered':len(match_ids),'public_match_reports_ok':len(match_rows)},'field_inventory':sorted(field_inventory),'governance':{'premium_surface_accessed':False,'authenticated_surface_accessed':False,'cross_provider_normalization_performed':False,'missing_values_filled':False,'predictive_models_modified':False,'decision_layer_started':False}}
    dump(OUT/'manifest.json',manifest)
    inv=[]
    for p in sorted(x for x in OUT.rglob('*') if x.is_file()):
        if p.name=='file-inventory.json': continue
        inv.append({'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    dump(OUT/'file-inventory.json',inv)
    print(json.dumps({'status':manifest['status'],'coverage':manifest['coverage'],'fields':manifest['field_inventory'],'files':len(inv)},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
