#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
import requests
BASE='https://fantaking-api.dunkest.com/api/v1'; LEAGUE=14; MATCHDAY=1469; PLAYER=5660
OUT=Path('/mnt/data/nexus-slgr-fantasy-public-probe-v7');RAW=OUT/'raw';RAW.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*','Referer':'https://fantasy.slgr.gr/','Origin':'https://fantasy.slgr.gr'})
def sha(b):return hashlib.sha256(b).hexdigest()
def get(route,params):
 r=s.get(BASE+route,params=params,timeout=45,allow_redirects=True);b=r.content
 m={'route':route,'params':params,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':sha(b),'preview':r.text[:1000]}
 try:
  o=r.json();m['json_type']=type(o).__name__;m['json_len']=len(o) if hasattr(o,'__len__') else None;m['json_keys']=list(o)[:120] if isinstance(o,dict) else None
 except Exception:o=None
 if r.status_code==200:(RAW/(route.strip('/').replace('/','__')+'.json')).write_bytes(b)
 return m,o
tests=[];objects={}
for route,params in [
 (f'/players/{PLAYER}/profile',{'league':LEAGUE}),
 (f'/players/{PLAYER}/fantasy-pts',{'league':LEAGUE,'matchday':MATCHDAY})
]:
 m,o=get(route,params);tests.append(m);objects[route]=o
# Inventory provider-native response shapes only.
def inventory(v,path='',rows=None):
 if rows is None:rows=[]
 if isinstance(v,dict):
  rows.append({'path':path or '$','keys':sorted(v.keys())[:200],'scalar_sample':{k:z for k,z in v.items() if not isinstance(z,(dict,list)) and z is not None}})
  for k,z in v.items():
   if isinstance(z,(dict,list)):inventory(z,f'{path}.{k}' if path else k,rows)
 elif isinstance(v,list):
  rows.append({'path':path or '$','list_len':len(v)})
  for i,z in enumerate(v[:50]):
   if isinstance(z,(dict,list)):inventory(z,f'{path}[{i}]',rows)
 return rows
shape={r:inventory(o)[:500] for r,o in objects.items() if o is not None}
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V7','api_base':BASE,'provider_ids':{'league_id':LEAGUE,'matchday_id':MATCHDAY,'player_id':PLAYER},'id_provenance':{'league_id':'compiled app config [14, slgr]','matchday_id':'public /leagues/14/fantasy-leaders?lang=en response','player_id':'same public fantasy-leaders response (Ayoub El Kaabi)'},'tests':tests,'response_shape_inventory':shape,'successful_reads':[x for x in tests if x.get('status')==200],'governance':{'only_compiled_app_contracts_with_provider_returned_ids_tested':True,'authenticated_surface_accessed':False,'user_team_private_routes_accessed':False,'bruteforce_endpoint_dictionary_used':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'tests':[(x['route'],x['status'],x.get('json_type'),x.get('json_len'),x.get('json_keys')) for x in tests]},ensure_ascii=False,indent=2))
