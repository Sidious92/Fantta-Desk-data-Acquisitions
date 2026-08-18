#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
import requests
BASE='https://fantaking-api.dunkest.com/api/v1'; LEAGUE=14
OUT=Path('/mnt/data/nexus-slgr-fantasy-public-probe-v6');RAW=OUT/'raw';RAW.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*','Referer':'https://fantasy.slgr.gr/','Origin':'https://fantasy.slgr.gr'})
def sha(b):return hashlib.sha256(b).hexdigest()
def get(route,params=None):
 r=s.get(BASE+route,params=params or {},timeout=45,allow_redirects=True);b=r.content
 m={'route':route,'params':params or {},'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':sha(b),'preview':r.text[:800]}
 try:
  o=r.json();m['json_type']=type(o).__name__;m['json_len']=len(o) if hasattr(o,'__len__') else None;m['json_keys']=list(o)[:100] if isinstance(o,dict) else None
 except Exception:o=None
 if r.status_code==200:(RAW/(route.strip('/').replace('/','__')+'.json')).write_bytes(b)
 return m,o
def walk(v,path='',out=None):
 if out is None:out=[]
 if isinstance(v,dict):
  idish={k:z for k,z in v.items() if (k=='id' or k.endswith('_id') or k in {'player','player_id','matchday','matchday_id','players_list_id','league_id','competition_id','schedule_id'}) and isinstance(z,(str,int,float))}
  if idish:out.append({'path':path,'ids':idish,'keys':sorted(v.keys())[:120]})
  for k,z in v.items():
   if isinstance(z,(dict,list)):walk(z,f'{path}.{k}' if path else k,out)
 elif isinstance(v,list):
  for i,z in enumerate(v[:5000]):
   if isinstance(z,(dict,list)):walk(z,f'{path}[{i}]',out)
 return out
# 'en' is not guessed: compiled app config explicitly maps supported language keys ['en', 'el'].
leader_meta,leaders=get(f'/leagues/{LEAGUE}/fantasy-leaders',{'lang':'en'})
id_nodes=walk(leaders) if leaders is not None else []
player_ids=[]
for node in id_nodes:
 ids=node['ids'];keys=node['keys']
 for k,v in ids.items():
  if k in {'player_id','player'}:player_ids.append(v)
 if 'id' in ids and any(x in keys for x in ['first_name','last_name','position','quotation','fantasy_pts','avg_points','player']):player_ids.append(ids['id'])
player_ids=list(dict.fromkeys(player_ids))
resolved=[]
if leader_meta['status']==200 and player_ids:
 pid=player_ids[0]
 for route,params in [
  (f'/players/{pid}/profile',None),
  (f'/players/{pid}/fantasy-pts',{'league':LEAGUE})
 ]:
  m,o=get(route,params);m['resolved_from_provider_player_id']=pid;resolved.append(m)
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V6','api_base':BASE,'league_id':LEAGUE,'language':'en','language_basis':'compiled app supported-language map [en, el]','fantasy_leaders':leader_meta,'id_nodes':id_nodes[:4000],'provider_player_ids_discovered':player_ids[:500],'resolved_player_tests':resolved,'successful_reads':[x for x in [leader_meta]+resolved if x.get('status')==200],'governance':{'only_compiled_app_get_contracts_tested':True,'authenticated_surface_accessed':False,'auth_required_injuries_route_retried':False,'user_team_private_routes_accessed':False,'bruteforce_endpoint_dictionary_used':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'leaders':(leader_meta['status'],leader_meta.get('json_type'),leader_meta.get('json_len')),'player_ids':player_ids[:20],'resolved':[(x['route'],x['status'],x.get('json_type'),x.get('json_len')) for x in resolved]},ensure_ascii=False,indent=2))
