#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
SITE='https://fantasy.slgr.gr/'
OUT=Path('/mnt/data/nexus-slgr-fantasy-public-probe-v1');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/javascript,application/json,*/*'})
def sha(b):return hashlib.sha256(b).hexdigest()
def meta(r):return {'requested':r.request.url,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(r.content),'sha256':sha(r.content),'preview':r.text[:1200]}
r=s.get(SITE,timeout=40,allow_redirects=True);r.raise_for_status();html=r.text
scripts=[];api_candidates=set();contexts=[]
for src in re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I):
 u=urljoin(r.url,src)
 try:
  rr=s.get(u,timeout=45,allow_redirects=True);t=rr.text;m=meta(rr)
  for needle in ['api','axios','fetch(','graphql','player','fantasy','statistics','baseURL','baseUrl']:
   for x in list(re.finditer(re.escape(needle),t,re.I))[:30]:contexts.append({'url':rr.url,'needle':needle,'text':t[max(0,x.start()-900):min(len(t),x.start()+1800)]})
  for x in re.findall(r'https?://[^"\'\s)]+',t):
   if any(k in x.lower() for k in ['api','fantasy','slgr','funatix']):api_candidates.add(x[:500])
  for x in re.findall(r'["\'](/(?:api|v1|v2|players?|statistics|teams?|clubs?|games?|matches?|rounds?|leaderboard|rankings?)[^"\']*)["\']',t,re.I):api_candidates.add(x)
  scripts.append(m)
 except Exception as e:scripts.append({'requested':u,'error':repr(e)})
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V1','site':meta(r),'scripts':scripts,'api_candidates':sorted(api_candidates),'contexts':contexts[:400],'governance':{'authenticated_surface_accessed':False,'private_endpoint_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'site':res['site'],'script_count':len(scripts),'api_candidates':res['api_candidates'][:100]},ensure_ascii=False,indent=2))
