#!/usr/bin/env python3
from __future__ import annotations

import csv, hashlib, json, os, shutil, time
from pathlib import Path
import requests

PIN='dec0b2d10aae1a1dff0b489b59fae4d2c8405ca3'
YEARS=[2021,2022,2023,2024,2025,2026]
ARCHIVE=Path('/mnt/data/cartola-archive')
OUT=Path('/mnt/data/nexus-cartola-fc-brasileirao-v1')
RAW=OUT/'raw'; HIST=RAW/'historical'; API_OUT=RAW/'current-api'
API='https://api.cartolafc.globo.com'
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*'})

def sha_bytes(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def sha_file(p:Path)->str:
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def dump(p:Path,o):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')

def fetch(path:str):
 url=API+path
 last=None
 for i in range(5):
  try:
   r=S.get(url,timeout=40,allow_redirects=True)
   if r.status_code==429:
    time.sleep(2**i);continue
   r.raise_for_status();return r
  except Exception as e:last=e;time.sleep(min(8,2**i))
 raise last or RuntimeError(url)

if OUT.exists():shutil.rmtree(OUT)
HIST.mkdir(parents=True);API_OUT.mkdir(parents=True)
if not (ARCHIVE/'.git').is_dir():raise SystemExit('archive clone missing')
head=os.popen(f'git -C {ARCHIVE} rev-parse HEAD').read().strip()
if head!=PIN:raise SystemExit(f'archive pin mismatch {head} != {PIN}')

# Preserve exact raw files. 2021 uses legacy Mercado_N.txt JSON; 2022+ uses rodada-N.csv.
year_stats={};historical_inventory=[];all_columns=set();total_rows=0;total_files=0
for year in YEARS:
 src=ARCHIVE/f'data/01_raw/{year}'
 if not src.is_dir():raise SystemExit(f'missing archive year {year}')
 dst=HIST/str(year);shutil.copytree(src,dst)
 csv_files=sorted(dst.glob('rodada-*.csv'))
 legacy_files=sorted(dst.glob('Mercado_*.txt'))
 rows=0;ids=set();cols=set();scout_cols=set();rounds=[]
 if csv_files:
  source_format='CSV_ROUND_SNAPSHOT'
  files=csv_files
  for p in files:
   with p.open('r',encoding='utf-8-sig',newline='') as f:
    rd=csv.DictReader(f); fields=rd.fieldnames or [];cols.update(fields);all_columns.update(fields)
    n=0
    for r in rd:
     n+=1
     pid=r.get('atletas.atleta_id') or r.get('atleta_id') or r.get('atletas_id')
     if pid not in (None,''):ids.add(str(pid))
    rows+=n
   try:rounds.append(int(p.stem.split('-')[-1]))
   except Exception:pass
   historical_inventory.append({'year':year,'format':source_format,'file':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':sha_file(p),'rows':n})
 elif legacy_files:
  source_format='LEGACY_MARKET_JSON_TXT'
  files=legacy_files
  for p in files:
   try:o=json.loads(p.read_text(encoding='utf-8'))
   except UnicodeDecodeError:o=json.loads(p.read_text(encoding='latin-1'))
   athletes=o.get('atletas') if isinstance(o,dict) else None
   if not isinstance(athletes,list):athletes=[]
   n=len(athletes);rows+=n
   for a in athletes:
    if not isinstance(a,dict):continue
    cols.update(a.keys());all_columns.update('atletas.'+k for k in a.keys())
    pid=a.get('atleta_id')
    if pid not in (None,''):ids.add(str(pid))
    sc=a.get('scout')
    if isinstance(sc,dict):scout_cols.update(sc.keys());all_columns.update(sc.keys())
   try:rounds.append(int(p.stem.split('_')[-1]))
   except Exception:pass
   historical_inventory.append({'year':year,'format':source_format,'file':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':sha_file(p),'rows':n})
 else:
  source_format='UNRECOGNIZED'
  files=[]
 year_stats[str(year)]={'source_format':source_format,'source_files':len(files),'rows':rows,'unique_player_ids':len(ids),'round_min':min(rounds) if rounds else None,'round_max':max(rounds) if rounds else None,'athlete_or_csv_columns':sorted(cols),'scout_fields':sorted(scout_cols)}
 total_rows+=rows;total_files+=len(files)

api_paths={'market_status':'/mercado/status','rounds':'/rodadas','clubs':'/clubes','matches':'/partidas','market_players':'/atletas/mercado','scored_players':'/atletas/pontuados'}
api_meta={};api_objs={}
for name,path in api_paths.items():
 try:
  r=fetch(path);b=r.content;(API_OUT/f'{name}.json').write_bytes(b)
  try:o=r.json()
  except Exception:o=None
  api_objs[name]=o
  api_meta[name]={'url':r.url,'status':r.status_code,'bytes':len(b),'sha256':sha_bytes(b),'json_type':type(o).__name__ if o is not None else None,'rows':len(o) if hasattr(o,'__len__') else None}
 except Exception as e:api_meta[name]={'url':API+path,'error':repr(e)}

market=api_objs.get('market_players') or {};athletes=market.get('atletas') if isinstance(market,dict) else None
if not isinstance(athletes,list):athletes=[]
market_fields=sorted({k for a in athletes if isinstance(a,dict) for k in a.keys()})
scout_fields=sorted({k for a in athletes if isinstance(a,dict) and isinstance(a.get('scout'),dict) for k in a['scout'].keys()})

manifest={'schema':'NEXUS_CARTOLA_FC_BRASILEIRAO_V1','status':'PASS','provider':'Cartola FC','competition':'Campeonato Brasileiro Serie A','archive':{'repository':'henriquepgomide/caRtola','pinned_commit':PIN,'observed_head':head,'years':YEARS,'year_stats':year_stats,'total_source_files':total_files,'total_rows':total_rows,'column_inventory':sorted(all_columns)},'current_api':{'base':API,'surfaces':api_meta,'market_players':len(athletes),'market_player_fields':market_fields,'market_scout_fields':scout_fields},'governance':{'authenticated_surface_accessed':False,'cross_provider_normalization_performed':False,'missing_values_filled':False,'predictive_models_modified':False,'decision_layer_started':False,'provider_native_fields_preserved':True,'historical_seasons_merged_at_ingest':False}}
checks={'archive_pin':head==PIN,'all_years':all((HIST/str(y)).is_dir() for y in YEARS),'each_year_nonempty':all(year_stats[str(y)]['source_files']>0 and year_stats[str(y)]['rows']>0 for y in YEARS),'source_files_gt_100':total_files>100,'historical_rows_gt_10000':total_rows>10000,'current_market_players_gt_100':len(athletes)>100,'no_auth':manifest['governance']['authenticated_surface_accessed'] is False,'no_model_mutation':manifest['governance']['predictive_models_modified'] is False}
manifest['validation']={'status':'PASS' if all(checks.values()) else 'FAIL','checks':checks};manifest['status']=manifest['validation']['status']
dump(OUT/'manifest.json',manifest);dump(OUT/'historical-file-inventory.json',historical_inventory)
inv=[]
for p in sorted(x for x in OUT.rglob('*') if x.is_file()):
 if p.name=='file-inventory.json':continue
 inv.append({'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':sha_file(p)})
dump(OUT/'file-inventory.json',inv)
print(json.dumps({'status':manifest['status'],'archive_files':total_files,'archive_rows':total_rows,'market_players':len(athletes),'year_stats':{y:{k:v for k,v in s.items() if k not in ('athlete_or_csv_columns','scout_fields')} for y,s in year_stats.items()}},ensure_ascii=False,indent=2))
raise SystemExit(0 if manifest['status']=='PASS' else 1)
