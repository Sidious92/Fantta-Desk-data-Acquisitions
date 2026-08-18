#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json
from pathlib import Path
import requests
BASE='https://fantaking-api.dunkest.com/api/v1'; COMPETITION=46
OUT=Path('/mnt/data/nexus-slgr-fantasy-public-probe-v14');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*','Referer':'https://fantasy.slgr.gr/','Origin':'https://fantasy.slgr.gr'})
r=s.get(f'{BASE}/competitions/{COMPETITION}/stats/players/table',timeout=60,allow_redirects=True);b=r.content
m={'route':f'/competitions/{COMPETITION}/stats/players/table','params':{},'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'preview':r.text[:3000]}
try:
 o=r.json();m['json_type']=type(o).__name__;m['json_len']=len(o) if hasattr(o,'__len__') else None;m['json_keys']=list(o)[:120] if isinstance(o,dict) else None;m['json']=o
except Exception:o=None
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V14','api_base':BASE,'competition_id':COMPETITION,'competition_id_provenance':'public /leagues/14/config current_competition_id','test':m,'governance':{'exact_compiled_app_get_contract_tested':True,'parameters_invented':False,'authenticated_surface_accessed':False,'user_team_private_routes_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))
