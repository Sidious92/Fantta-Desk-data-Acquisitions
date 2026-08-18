#!/usr/bin/env python3
from __future__ import annotations
import csv,hashlib,json,os,shutil,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
import requests
BASE='https://api.mpg.football/fantasy'; CHAMPIONSHIP_ID=1
OUT=Path('/mnt/data/nexus-ligue1-official-fantasy-v1'); RAW=OUT/'raw'; NORM=OUT/'normalized'
HEADERS={'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*','Referer':'https://ligue1.com/en/fantasy','platform':'web','application':'ligue1'}
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def mkdir(p):p.mkdir(parents=True,exist_ok=True);return p
def dump(p,o):mkdir(p.parent);p.write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def get(route,attempts=5):
 url=BASE+route;last=None
 for i in range(attempts):
  try:
   r=requests.get(url,headers=HEADERS,timeout=40,allow_redirects=True)
   if r.status_code==429:
    time.sleep(min(20,1.5*(2**i)));continue
   if r.status_code==200:return r
   last=RuntimeError(f'HTTP_{r.status_code} {r.url} {r.text[:250]!r}')
  except Exception as e:last=e
  time.sleep(min(8,.6*(2**i)))
 raise last or RuntimeError(url)
def scalar(d):return {k:v for k,v in d.items() if not isinstance(v,(dict,list))}
def write_csv(p,rows):
 mkdir(p.parent)
 if not rows:p.write_text('',encoding='utf-8');return
 fs=[];seen=set()
 for row in rows:
  for k in row:
   if k not in seen:seen.add(k);fs.append(k)
 with p.open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=fs);w.writeheader();w.writerows(rows)
def file_inv():
 inv=[]
 for p in sorted(x for x in OUT.rglob('*') if x.is_file()):
  if p.name=='file-inventory.json':continue
  inv.append({'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 return inv
if OUT.exists():shutil.rmtree(OUT)
mkdir(RAW);mkdir(NORM);started=now()
# Exact anonymous GET surfaces proven by frontend tracing and probe v9.
surfaces={
 'players_pool':'/championship-players-pool/1?addPlayersStatuses=true',
 'clubs':'/championships-clubs',
 'settings':'/championships-settings',
 'rules':'/rules'
}
objs={};meta={}
for name,route in surfaces.items():
 r=get(route);b=r.content;(RAW/f'{name}.json').write_bytes(b);o=r.json();objs[name]=o
 meta[name]={'route':route,'url':r.url,'status':r.status_code,'bytes':len(b),'sha256':sha(b),'json_type':type(o).__name__,'json_len':len(o) if hasattr(o,'__len__') else None}
pool=objs['players_pool'];players=pool.get('players') if isinstance(pool,dict) else None
if not isinstance(players,list):raise SystemExit('players pool missing list')
clubs=objs['clubs'];club_count=len(clubs) if isinstance(clubs,dict) else 0
# Preserve pool rows exactly while offering a scalar index for inspection.
pool_rows=[];pool_fields=set();pool_stats_fields=set()
for p in players:
 if not isinstance(p,dict):continue
 pool_fields.update(p.keys())
 if isinstance(p.get('stats'),dict):pool_stats_fields.update(p['stats'].keys())
 pool_rows.append({'provider':'LIGUE1_OFFICIAL_FANTASY','competition':'Ligue 1','championship_id':CHAMPIONSHIP_ID,'provider_player_id':p.get('id'),'provider_club_id':p.get('clubId'),'provider_fields_json':json.dumps(p,ensure_ascii=False,separators=(',',':'),default=str),**scalar(p),'stats_json':json.dumps(p.get('stats'),ensure_ascii=False,separators=(',',':'),default=str) if isinstance(p.get('stats'),dict) else None})
write_csv(NORM/'players-pool.csv',pool_rows)
# Public player detail route, one real provider id per player. No auth/private routes.
detail_dir=mkdir(RAW/'player-details');detail_rows=[];errors=[];detail_fields=set();prev_fields=set();prev_rows=[]
def one(p):
 pid=p.get('id') if isinstance(p,dict) else None
 if not pid:return {'id':pid,'error':'MISSING_PROVIDER_ID'}
 route=f'/championship-player-stats/{pid}/championship/{CHAMPIONSHIP_ID}'
 try:
  r=get(route);b=r.content;o=r.json();lp=detail_dir/f'{pid}.json';lp.write_bytes(b)
  return {'id':pid,'obj':o,'url':r.url,'sha256':sha(b),'path':lp}
 except Exception as e:return {'id':pid,'error':repr(e)}
with ThreadPoolExecutor(max_workers=5) as ex:
 futs=[ex.submit(one,p) for p in players if isinstance(p,dict)]
 for fut in as_completed(futs):
  x=fut.result();pid=x.get('id')
  if x.get('error'):
   errors.append({'provider_player_id':pid,'error':x['error']});continue
  o=x['obj']
  if isinstance(o,dict):detail_fields.update(o.keys())
  prev=o.get('previousMatches') if isinstance(o,dict) else None
  if isinstance(prev,list):
   for m in prev:
    if isinstance(m,dict):
     prev_fields.update(m.keys());prev_rows.append({'provider':'LIGUE1_OFFICIAL_FANTASY','competition':'Ligue 1','championship_id':CHAMPIONSHIP_ID,'provider_player_id':pid,'provider_fields_json':json.dumps(m,ensure_ascii=False,separators=(',',':'),default=str),**scalar(m)})
  detail_rows.append({'provider':'LIGUE1_OFFICIAL_FANTASY','competition':'Ligue 1','championship_id':CHAMPIONSHIP_ID,'provider_player_id':pid,'source_url':x['url'],'source_sha256':x['sha256'],'source_local_path':str(x['path'].relative_to(OUT)),'provider_fields_json':json.dumps(o,ensure_ascii=False,separators=(',',':'),default=str),**scalar(o),'previous_matches_json':json.dumps(prev,ensure_ascii=False,separators=(',',':'),default=str) if isinstance(prev,list) else None,'next_match_json':json.dumps(o.get('nextMatch'),ensure_ascii=False,separators=(',',':'),default=str) if isinstance(o,dict) and isinstance(o.get('nextMatch'),(dict,list)) else None,'assets_json':json.dumps(o.get('assets'),ensure_ascii=False,separators=(',',':'),default=str) if isinstance(o,dict) and isinstance(o.get('assets'),(dict,list)) else None})
write_csv(NORM/'player-detail-index.csv',detail_rows);write_csv(NORM/'previous-matches.csv',prev_rows);dump(OUT/'player-detail-errors.json',errors)
settings=objs['settings'];season_info=None
if isinstance(settings,dict):season_info=((settings.get('championshipsSettings') or {}).get(str(CHAMPIONSHIP_ID)) if isinstance(settings.get('championshipsSettings'),dict) else None)
rate=len(detail_rows)/len(players) if players else 0
checks={
 'players_ge_400':len(players)>=400,
 'clubs_ge_16':club_count>=16,
 'player_detail_rate_ge_095':rate>=0.95,
 'settings_200':meta['settings']['status']==200,
 'rules_200':meta['rules']['status']==200,
 'no_auth':True,
 'no_model_mutation':True,
 'no_decision_layer':True
}
status='PASS' if all(checks.values()) else 'FAIL'
manifest={
 'schema':'NEXUS_LIGUE1_OFFICIAL_FANTASY_ACQUISITION_V1',
 'status':status,
 'provider':'Ligue 1 Official Fantasy',
 'competition':'Ligue 1',
 'championship_id':CHAMPIONSHIP_ID,
 'capture_started':started,
 'capture_completed':now(),
 'source':{'official_frontend':'https://ligue1.com/en/fantasy','fantasy_api_base':BASE,'surfaces':meta},
 'coverage':{'players':len(players),'clubs':club_count,'player_details_ok':len(detail_rows),'player_detail_errors':len(errors),'player_detail_success_rate':rate,'previous_match_rows':len(prev_rows)},
 'field_inventory':{'player_pool_fields':sorted(pool_fields),'player_pool_stats_fields':sorted(pool_stats_fields),'player_detail_fields':sorted(detail_fields),'previous_match_fields':sorted(prev_fields)},
 'season_context':season_info,
 'temporal_semantics':{'bulk_and_player_detail':'CURRENT_PROVIDER_SEASON_AT_CAPTURE','historical_season_claim':'NONE_UNTIL_EMPIRICALLY_VERIFIED','previousMatches':'PROVIDER_NATIVE_CURRENT_SEASON_MATCH_EVIDENCE'},
 'governance':{'authenticated_surface_accessed':False,'private_user_or_coach_routes_accessed':False,'cross_provider_normalization_performed':False,'missing_values_filled':False,'historical_seasons_merged_at_ingest':False,'provider_native_fields_preserved':True,'predictive_models_modified':False,'decision_layer_started':False},
 'validation':{'status':status,'checks':checks}
}
dump(OUT/'manifest.json',manifest);dump(OUT/'file-inventory.json',file_inv())
print(json.dumps({'status':status,'players':len(players),'clubs':club_count,'details_ok':len(detail_rows),'errors':len(errors),'rate':rate,'previous_match_rows':len(prev_rows),'season_context':season_info,'pool_stats_fields':sorted(pool_stats_fields),'previous_match_fields':sorted(prev_fields)},ensure_ascii=False,indent=2))
raise SystemExit(0 if status=='PASS' else 1)
