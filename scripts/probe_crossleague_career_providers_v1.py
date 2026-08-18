#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,time
from pathlib import Path
from urllib.parse import quote
import requests
OUT=Path('/mnt/data/nexus-crossleague-career-provider-probe-v1');OUT.mkdir(parents=True,exist_ok=True)
PLAYERS=['Matija Frigan','Andrea Adorante','Kornel Lisman','Albion Rrahmani']
HEADERS={'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*'}
def sha(b):return hashlib.sha256(b).hexdigest()
def call(label,url,headers=None):
 try:
  r=requests.get(url,headers=headers or HEADERS,timeout=(8,25),allow_redirects=True);b=r.content
  x={'label':label,'requested':url,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':sha(b),'preview':r.text[:1200]}
  try:
   o=r.json();x['json_type']=type(o).__name__;x['json_len']=len(o) if hasattr(o,'__len__') else None;x['json_keys']=list(o)[:100] if isinstance(o,dict) else None;x['json']=o
  except Exception:o=None
  return x,o
 except Exception as e:return {'label':label,'requested':url,'error':repr(e)},None
results={'schema':'NEXUS_CROSSLEAGUE_CAREER_PROVIDER_PROBE_V1','players':PLAYERS,'providers':{},'governance':{'authenticated_surface_accessed':False,'private_routes_accessed':False,'bruteforce_ids':False,'predictive_models_modified':False,'decision_layer_started':False}}
# Sofascore official public search surface.
sofa=[]
for name in PLAYERS:
 x,o=call('sofascore_search',f'https://www.sofascore.com/api/v1/search/all?q={quote(name)}');sofa.append({'player':name,'search':x})
 time.sleep(.3)
results['providers']['sofascore']={'official_domain':'www.sofascore.com','tests':sofa}
# FotMob official public search/suggest surfaces: test only known frontend-compatible suggestions, no guessed player ids.
fot=[]
for name in PLAYERS:
 tests=[]
 for url in [
  f'https://www.fotmob.com/api/searchapi/suggest?term={quote(name)}',
  f'https://www.fotmob.com/api/search/suggest?term={quote(name)}'
 ]:
  x,o=call('fotmob_search',url,{'User-Agent':HEADERS['User-Agent'],'Accept':'application/json,text/plain,*/*','Referer':'https://www.fotmob.com/'});tests.append(x)
  if x.get('status')==200 and o is not None:break
 fot.append({'player':name,'search_tests':tests});time.sleep(.3)
results['providers']['fotmob']={'official_domain':'www.fotmob.com','tests':fot}
(OUT/'RESULT.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'sofascore':[(x['player'],x['search'].get('status'),x['search'].get('json_type'),x['search'].get('json_keys')) for x in sofa],'fotmob':[(x['player'],[(y.get('status'),y.get('json_type'),y.get('json_keys')) for y in x['search_tests']]) for x in fot]},ensure_ascii=False,indent=2))
