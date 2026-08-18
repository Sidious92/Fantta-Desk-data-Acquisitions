#!/usr/bin/env python3
import concurrent.futures, csv, hashlib, json, time
from pathlib import Path
import requests

BASE='https://fantasy.ligaportugal.pt/api/'
OUT=Path('/mnt/data/nexus-liga-portugal-fantasy-v1')
RAW=OUT/'raw'; PROFILES=RAW/'element-summary'; OUT.mkdir(parents=True,exist_ok=True); PROFILES.mkdir(parents=True,exist_ok=True)
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition'})

def sha(b): return hashlib.sha256(b).hexdigest()
def fetch_json(path, timeout=40):
    url=BASE+path
    r=S.get(url,timeout=timeout); r.raise_for_status(); b=r.content; j=r.json()
    return url,b,j

def save_raw(name,b):
    p=RAW/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b); return str(p.relative_to(OUT))

started=time.time(); errors=[]; sources={}
for key,path,name in [('bootstrap','bootstrap-static/','bootstrap-static.json'),('fixtures','fixtures/','fixtures.json')]:
    url,b,j=fetch_json(path); lp=save_raw(name,b)
    sources[key]={'url':url,'bytes':len(b),'sha256':sha(b),'local_path':lp,'json_type':type(j).__name__,'rows':len(j) if hasattr(j,'__len__') else None}
    if key=='bootstrap': bootstrap=j

players=bootstrap.get('elements') or []
teams=bootstrap.get('teams') or []
events=bootstrap.get('events') or []

def one(player):
    pid=player['id']; path=f'element-summary/{pid}/'
    try:
        url,b,j=fetch_json(path)
        lp=PROFILES/f'{pid}.json'; lp.write_bytes(b)
        return {'id':pid,'ok':True,'url':url,'bytes':len(b),'sha256':sha(b),'history_rows':len(j.get('history') or []),'history_past_rows':len(j.get('history_past') or []),'fixtures_rows':len(j.get('fixtures') or []),'json':j}
    except Exception as e:
        return {'id':pid,'ok':False,'error':repr(e)}

results=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
    for x in ex.map(one,players): results.append(x)

ok=[x for x in results if x['ok']]; bad=[x for x in results if not x['ok']]
for x in bad: errors.append({'player_id':x['id'],'error':x['error']})

# Provider-native flattened JSONL, with player identity attached but no cross-provider normalization.
current_rows=[]; past_rows=[]; profile_index=[]
by_id={p['id']:p for p in players}
for x in ok:
    p=by_id[x['id']]; base={'provider_player_id':p['id'],'web_name':p.get('web_name'),'first_name':p.get('first_name'),'second_name':p.get('second_name'),'team_id':p.get('team'),'element_type':p.get('element_type')}
    for h in x['json'].get('history') or []:
        current_rows.append({**base,**h})
    for h in x['json'].get('history_past') or []:
        past_rows.append({**base,**h})
    profile_index.append({k:v for k,v in x.items() if k!='json'})

with open(OUT/'current_history.jsonl','w',encoding='utf-8') as f:
    for r in current_rows: f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
with open(OUT/'history_past.jsonl','w',encoding='utf-8') as f:
    for r in past_rows: f.write(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n')
(OUT/'profile-index.json').write_text(json.dumps(profile_index,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

manifest={
 'schema':'NEXUS_LIGA_PORTUGAL_FANTASY_V1',
 'status':'PASS' if players and len(ok)/len(players)>=0.95 else 'FAIL',
 'provider':'Fantasy Liga Portugal Betclic',
 'api_base':BASE,
 'capture_started_epoch':started,
 'capture_completed_epoch':time.time(),
 'coverage':{
   'players':len(players),'teams':len(teams),'events':len(events),
   'profiles_ok':len(ok),'profile_errors':len(bad),'profile_success_rate':(len(ok)/len(players) if players else 0),
   'current_history_rows':len(current_rows),'history_past_rows':len(past_rows),
   'players_with_history_past':sum(1 for x in ok if x['history_past_rows']>0)
 },
 'sources':sources,
 'bootstrap_fields':list(bootstrap.keys()),
 'element_fields':sorted({k for p in players for k in p.keys()}),
 'current_history_fields':sorted({k for r in current_rows for k in r.keys()}),
 'history_past_fields':sorted({k for r in past_rows for k in r.keys()}),
 'errors':errors,
 'governance':{
   'authenticated_surface_accessed':False,
   'cross_provider_normalization_performed':False,
   'missing_values_filled':False,
   'predictive_models_modified':False,
   'decision_layer_started':False,
   'provider_native_fields_preserved':True
 }
}
(OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(manifest['coverage'],indent=2))
raise SystemExit(0 if manifest['status']=='PASS' else 1)
