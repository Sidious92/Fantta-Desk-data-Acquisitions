#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,time,shutil
from pathlib import Path
import requests

BASE='https://fantasy.spl.com.sa/api/'
OUT=Path('/mnt/data/nexus-rsl-fantasy-v1'); RAW=OUT/'raw'; PROF=RAW/'element-summary'; EVENTS=RAW/'events'
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*','Referer':'https://fantasy.spl.com.sa/'})

def sha(b):return hashlib.sha256(b).hexdigest()
def dump(p,o):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def fetch(path,retry=True):
 url=BASE+path; waits=[0,1,2,4,8,16,24] if retry else [0]; last=None
 for w in waits:
  if w:time.sleep(w)
  try:
   r=S.get(url,timeout=40,allow_redirects=True);last=r
   if r.status_code==429 and retry:continue
   r.raise_for_status();return r
  except Exception as e:last=e
 if isinstance(last,requests.Response):last.raise_for_status()
 raise last or RuntimeError(url)

def save(p,b):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)

if OUT.exists():shutil.rmtree(OUT)
PROF.mkdir(parents=True);EVENTS.mkdir(parents=True)
started=time.time();errors=[]
rb=fetch('bootstrap-static/'); bootstrap=rb.json(); save(RAW/'bootstrap-static.json',rb.content)
players=bootstrap.get('elements') or []
events=bootstrap.get('events') or []
teams=bootstrap.get('teams') or []

profiles=[];current=[];past=[]
for i,p in enumerate(players,1):
 pid=p.get('id')
 if pid is None:continue
 try:
  r=fetch(f'element-summary/{pid}/');o=r.json();save(PROF/f'{pid}.json',r.content)
  h=o.get('history') or [];hp=o.get('history_past') or []
  base={'provider_player_id':pid,'web_name':p.get('web_name'),'first_name':p.get('first_name'),'second_name':p.get('second_name'),'team_id':p.get('team'),'element_type':p.get('element_type')}
  for x in h:
   if isinstance(x,dict):current.append({**base,**x})
  for x in hp:
   if isinstance(x,dict):past.append({**base,**x})
  profiles.append({'id':pid,'ok':True,'url':r.url,'bytes':len(r.content),'sha256':sha(r.content),'history_rows':len(h),'history_past_rows':len(hp)})
 except Exception as e:
  profiles.append({'id':pid,'ok':False,'error':repr(e)});errors.append({'surface':'element-summary','player_id':pid,'error':repr(e)})
 time.sleep(.15)
 if i%100==0:print(f'profiles {i}/{len(players)}',flush=True)

fixture_ok=0;live_ok=0;fixture_err=[];live_err=[]
for e in events:
 eid=e.get('id')
 if eid is None:continue
 try:
  r=fetch(f'fixtures/?event={eid}');save(EVENTS/f'fixtures-{eid}.json',r.content);fixture_ok+=1
 except Exception as ex:fixture_err.append({'event':eid,'error':repr(ex)})
 # live can legitimately be unavailable for future rounds; preserve successful reads only.
 try:
  r=fetch(f'event/{eid}/live/',retry=False);save(EVENTS/f'live-{eid}.json',r.content);live_ok+=1
 except Exception as ex:live_err.append({'event':eid,'error':repr(ex)})
 time.sleep(.10)

# dream-team is anonymous and provider-native, useful but nonessential.
dream=None
try:
 r=fetch('dream-team/',retry=False);save(RAW/'dream-team.json',r.content);dream={'status':r.status_code,'url':r.url,'bytes':len(r.content),'sha256':sha(r.content)}
except Exception as e:dream={'error':repr(e)}

with (OUT/'current_history.jsonl').open('w',encoding='utf-8') as f:
 for x in current:f.write(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n')
with (OUT/'history_past.jsonl').open('w',encoding='utf-8') as f:
 for x in past:f.write(json.dumps(x,ensure_ascii=False,separators=(',',':'))+'\n')
dump(OUT/'profile-index.json',profiles);dump(OUT/'fixture-errors.json',fixture_err);dump(OUT/'live-errors.json',live_err)
ok=sum(1 for x in profiles if x.get('ok')); rate=ok/len(players) if players else 0
fixture_rate=fixture_ok/len(events) if events else 0
manifest={
 'schema':'NEXUS_RSL_FANTASY_V1','status':'PASS' if players and rate>=.95 and fixture_rate>=.90 else 'FAIL',
 'provider':'RSL Fantasy','competition':'Saudi Pro League','api_base':BASE,
 'capture_started_epoch':started,'capture_completed_epoch':time.time(),
 'coverage':{'players':len(players),'teams':len(teams),'events':len(events),'profiles_ok':ok,'profile_errors':len(players)-ok,'profile_success_rate':rate,'current_history_rows':len(current),'history_past_rows':len(past),'players_with_history_past':sum(1 for x in profiles if x.get('history_past_rows',0)>0),'fixture_events_ok':fixture_ok,'fixture_event_errors':len(fixture_err),'fixture_success_rate':fixture_rate,'live_events_ok':live_ok,'live_event_errors':len(live_err)},
 'bootstrap':{'url':rb.url,'bytes':len(rb.content),'sha256':sha(rb.content),'keys':list(bootstrap.keys()),'element_fields':sorted({k for p in players if isinstance(p,dict) for k in p})},
 'current_history_fields':sorted({k for x in current for k in x}),'history_past_fields':sorted({k for x in past for k in x}),'dream_team':dream,'errors':errors,
 'governance':{'authenticated_surface_accessed':False,'private_user_or_league_routes_accessed':False,'cross_provider_normalization_performed':False,'missing_values_filled':False,'predictive_models_modified':False,'decision_layer_started':False,'historical_seasons_merged_at_ingest':False,'provider_native_fields_preserved':True}
}
dump(OUT/'manifest.json',manifest)
inv=[]
for p in sorted(x for x in OUT.rglob('*') if x.is_file()):
 if p.name=='file-inventory.json':continue
 inv.append({'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())})
dump(OUT/'file-inventory.json',inv)
print(json.dumps(manifest['coverage'],indent=2))
raise SystemExit(0 if manifest['status']=='PASS' else 1)
