#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
import requests
BASE='https://api.mpg.football/fantasy'
SUMMARY=Path('.nexus-ligue1-official-fantasy-api-probe-v8-status/SUMMARY.json')
OUT=Path('/mnt/data/nexus-ligue1-official-fantasy-api-probe-v9');RAW=OUT/'raw';RAW.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*','Referer':'https://ligue1.com/en/fantasy','platform':'web','application':'ligue1'})
def sha(b):return hashlib.sha256(b).hexdigest()
def safe_name(route):return re.sub(r'[^A-Za-z0-9._-]+','_',route.strip('/'))[:160] or 'root'
def request(route):
 r=s.get(BASE+route,timeout=40,allow_redirects=True);b=r.content
 m={'route':route,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':sha(b)}
 try:
  o=r.json();m['json_type']=type(o).__name__;m['json_len']=len(o) if hasattr(o,'__len__') else None;m['json_keys']=list(o)[:100] if isinstance(o,dict) else None
 except Exception:o=None;m['preview']=r.text[:500]
 if r.status_code==200:(RAW/(safe_name(route)+'.json')).write_bytes(b)
 return m,o
obj=json.loads(SUMMARY.read_text(encoding='utf-8'))
public=[c for c in obj.get('public_context_candidates',[]) if c.get('method')=='GET' and not c.get('auth_context_markers')]
routes=sorted({r for c in public for r in (c.get('route_candidates') or [])})
# Test only exact literal routes proven by frontend; never auth/user/coach/profile routes.
blocked_tokens=['/api/auth','/coach','/user','/profile','/my-team','/entry','/league']
literals=[r for r in routes if '${' not in r and r.startswith('/') and not any(x in r.lower() for x in blocked_tokens)]
tests=[];objects={}
# Player pool first because it provides a real provider player id for the parameterized player-stats route.
priority='/championship-players-pool/1?addPlayersStatuses=true'
if priority in literals:
 m,o=request(priority);tests.append(m);objects[priority]=o;literals.remove(priority)
for route in literals:
 m,o=request(route);tests.append(m);objects[route]=o
# Inspect player pool without assuming response shape.
pool=objects.get(priority);players=[]
def find_player_lists(v,path=''):
 out=[]
 if isinstance(v,list) and v and all(isinstance(x,dict) for x in v[:min(len(v),5)]):
  keys=set().union(*(x.keys() for x in v[:min(len(v),20)]))
  if {'id'} <= keys and any(k in keys for k in ['firstName','lastName','name','position','clubId','championshipClubId']):out.append((path,v))
 if isinstance(v,dict):
  for k,z in v.items():out.extend(find_player_lists(z,f'{path}.{k}' if path else k))
 elif isinstance(v,list):
  for i,z in enumerate(v[:20]):
   if isinstance(z,(dict,list)):out.extend(find_player_lists(z,f'{path}[{i}]'))
 return out
lists=find_player_lists(pool)
if lists:
 lists.sort(key=lambda x:len(x[1]),reverse=True);players=lists[0][1]
pool_summary={'candidate_player_lists':[{'path':p,'rows':len(v),'field_inventory':sorted({k for x in v if isinstance(x,dict) for k in x.keys()})} for p,v in lists[:10]],'selected_rows':len(players)}
# Resolve only the exact template proven by frontend using a real id and championship 1.
param_tests=[]
if players:
 sample=next((p for p in players if p.get('id') is not None),None)
 if sample:
  route=f"/championship-player-stats/{sample['id']}/championship/1"
  m,o=request(route);m['resolved_from_template']='/championship-player-stats/${e}/championship/${t}';m['sample_player_id']=sample['id'];param_tests.append(m)
# Compact successful response inventories.
success=[]
for m in tests+param_tests:
 if m.get('status')==200:success.append(m)
res={'schema':'NEXUS_LIGUE1_OFFICIAL_FANTASY_API_PUBLIC_PROBE_V9','source_summary_schema':obj.get('schema'),'base':BASE,'frontend_proven_public_get_routes':routes,'tested_literal_routes':[m['route'] for m in tests],'tests':tests,'pool_summary':pool_summary,'parameterized_tests':param_tests,'successful_reads':success,'governance':{'only_frontend_proven_get_routes_tested':True,'authenticated_surface_accessed':False,'private_user_or_coach_routes_accessed':False,'bruteforce_endpoint_dictionary_used':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'routes_discovered':routes,'tests':[(x['route'],x['status'],x.get('json_type'),x.get('json_len')) for x in tests],'pool_selected_rows':len(players),'param_tests':[(x['route'],x['status'],x.get('json_type'),x.get('json_len')) for x in param_tests]},ensure_ascii=False,indent=2))
