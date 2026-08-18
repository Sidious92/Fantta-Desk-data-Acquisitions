#!/usr/bin/env python3
import hashlib,json
from pathlib import Path
import requests
BASE='https://api.mpg.football/fantasy'
OUT=Path('/mnt/data/nexus-ligue1-official-fantasy-api-probe-v2');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*','Origin':'https://ligue1.com','Referer':'https://ligue1.com/en/fantasy'})
paths=['','/','/health','/version','/openapi.json','/swagger.json','/docs','/players','/clubs','/teams','/gameweeks','/rounds','/matchdays','/ratings','/standings','/ranking','/rules','/config','/settings','/public/players','/public/clubs','/public/gameweeks','/v1/players','/v1/clubs','/v1/gameweeks']
res={'schema':'NEXUS_LIGUE1_OFFICIAL_FANTASY_API_PUBLIC_PROBE_V2','base':BASE,'tests':[]}
for p in paths:
 u=BASE+p
 try:
  r=s.get(u,timeout=25,allow_redirects=True);b=r.content
  x={'path':p or '/','requested':u,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'preview':r.text[:1500]}
  try:
   j=r.json();x['json_type']=type(j).__name__;x['json_keys']=list(j)[:80] if isinstance(j,dict) else None;x['json_len']=len(j) if hasattr(j,'__len__') else None
  except Exception:pass
  res['tests'].append(x)
 except Exception as e:res['tests'].append({'path':p or '/','requested':u,'error':repr(e)})
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps([(x['path'],x.get('status'),x.get('json_keys')) for x in res['tests']],indent=2))
