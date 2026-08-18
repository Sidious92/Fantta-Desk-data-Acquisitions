#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
import requests
OUT=Path('/mnt/data/nexus-fotmob-playerdata-probe-v1');OUT.mkdir(parents=True,exist_ok=True)
PLAYERS=[
 {'name':'Matija Frigan','id':1190371,'public_page':'https://www.fotmob.com/it/players/1190371/matija-frigan'},
 {'name':'Andrea Adorante','id':1024432,'public_page':'https://www.fotmob.com/it/players/1024432/andrea-adorante'},
 {'name':'Kornel Lisman','id':1529483,'public_page':'https://www.fotmob.com/it/players/1529483/kornel-lisman'},
 {'name':'Albion Rrahmani','id':1379468,'public_page':'https://www.fotmob.com/it/players/1379468/albion-rrahmani'}
]
HEADERS={'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*','Referer':'https://www.fotmob.com/'}
def sha(b):return hashlib.sha256(b).hexdigest()
rows=[]
for p in PLAYERS:
 url=f"https://www.fotmob.com/api/playerData?id={p['id']}"
 try:
  r=requests.get(url,headers=HEADERS,timeout=(8,30),allow_redirects=True);b=r.content
  x={**p,'endpoint':url,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':sha(b),'preview':r.text[:1200]}
  try:
   o=r.json();x['json_type']=type(o).__name__;x['json_len']=len(o) if hasattr(o,'__len__') else None;x['json_keys']=list(o)[:120] if isinstance(o,dict) else None;x['json']=o
  except Exception:o=None
  rows.append(x)
 except Exception as e:rows.append({**p,'endpoint':url,'error':repr(e)})
res={'schema':'NEXUS_FOTMOB_PLAYERDATA_PUBLIC_PROBE_V1','players':rows,'governance':{'player_ids_from_verified_public_fotmob_pages':True,'search_endpoint_guessing_used':False,'authenticated_surface_accessed':False,'private_routes_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'players':[(x['name'],x.get('status'),x.get('json_type'),x.get('json_keys'),x.get('bytes')) for x in rows]},ensure_ascii=False,indent=2))
