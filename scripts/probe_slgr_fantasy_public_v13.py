#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
import requests
BASE='https://fantaking-api.dunkest.com/api/v1'; LEAGUE=14
OUT=Path('/mnt/data/nexus-slgr-fantasy-public-probe-v13');RAW=OUT/'raw';RAW.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*','Referer':'https://fantasy.slgr.gr/','Origin':'https://fantasy.slgr.gr'})
def sha(b):return hashlib.sha256(b).hexdigest()
def get(route,params=None):
 r=s.get(BASE+route,params=params or {},timeout=60,allow_redirects=True);b=r.content
 m={'route':route,'params':params or {},'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':sha(b),'preview':r.text[:1000]}
 try:
  o=r.json();m['json_type']=type(o).__name__;m['json_len']=len(o) if hasattr(o,'__len__') else None;m['json_keys']=list(o)[:120] if isinstance(o,dict) else None
 except Exception:o=None
 if r.status_code==200:(RAW/(route.strip('/').replace('/','__')+'.json')).write_bytes(b)
 return m,o
config_meta,config=get(f'/leagues/{LEAGUE}/config')
# Parser dKT proves these provider-native fields exist in config response.
data=config.get('data') if isinstance(config,dict) and isinstance(config.get('data'),dict) else config if isinstance(config,dict) else {}
ids={k:data.get(k) for k in ['status_id','current_competition_id','current_schedule_id','current_players_list_id']}
cm=data.get('current_matchday') if isinstance(data,dict) else None
if isinstance(cm,dict):
 ids['current_matchday_id']=cm.get('id');ids['current_matchday_number']=cm.get('number');ids['current_matchday_num_rounds']=cm.get('num_rounds')
# Use only IDs returned by the public config response.
tests=[config_meta];objects={'config':config}
plid=ids.get('current_players_list_id');mid=ids.get('current_matchday_id');sid=ids.get('current_schedule_id')
if config_meta['status']==200 and plid is not None and mid is not None:
 route=f'/players-lists/{plid}/matchdays/{mid}/players'
 m,o=get(route,{'per_page':-1,'page':1});m['resolved_from_config']={'players_list_id':plid,'matchday_id':mid};tests.append(m);objects['roster']=o
if config_meta['status']==200 and sid is not None and mid is not None:
 route=f'/schedules/{sid}/matchdays/{mid}'
 m,o=get(route);m['resolved_from_config']={'schedule_id':sid,'matchday_id':mid};tests.append(m);objects['matchday']=o
# Inventory roster shape without assumptions.
def find_lists(v,path=''):
 out=[]
 if isinstance(v,list):
  if v and all(isinstance(x,dict) for x in v[:min(10,len(v))]):
   keys=sorted({k for x in v[:min(100,len(v))] for k in x.keys()});out.append({'path':path or '$','rows':len(v),'keys':keys})
  for i,z in enumerate(v[:30]):
   if isinstance(z,(dict,list)):out.extend(find_lists(z,f'{path}[{i}]'))
 elif isinstance(v,dict):
  for k,z in v.items():
   if isinstance(z,(dict,list)):out.extend(find_lists(z,f'{path}.{k}' if path else k))
 return out
inventories={k:find_lists(v)[:100] for k,v in objects.items() if v is not None}
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V13','api_base':BASE,'league_id':LEAGUE,'league_id_basis':'compiled app config [14, slgr]','config_ids':ids,'tests':tests,'response_list_inventories':inventories,'successful_reads':[x for x in tests if x.get('status')==200],'governance':{'only_compiled_app_get_contracts_tested':True,'all_dynamic_ids_resolved_from_public_provider_config':True,'authenticated_surface_accessed':False,'user_team_private_routes_accessed':False,'bruteforce_endpoint_dictionary_used':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'config':(config_meta['status'],ids),'tests':[(x['route'],x['status'],x.get('json_type'),x.get('json_len'),x.get('bytes')) for x in tests],'inventories':inventories},ensure_ascii=False,indent=2))
