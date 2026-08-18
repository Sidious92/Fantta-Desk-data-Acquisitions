#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
PAGES=['https://fantasy.bundesliga.com/','https://www.bundesliga.com/en/bundesliga/fantasy-manager']
OUT=Path('/mnt/data/nexus-bundesliga-official-fantasy-probe-v1');OUT.mkdir(parents=True,exist_ok=True)
HEADERS={'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/javascript,application/json,*/*'}
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def fetch(u,timeout=18):return requests.get(u,headers=HEADERS,timeout=(8,timeout),allow_redirects=True)
def meta(r,u):return {'requested':u,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(r.content),'sha256':sha(r.content),'preview':r.text[:1200]}
page_results=[];script_owners={}
for p in PAGES:
 try:
  r=fetch(p,20);page_results.append(meta(r,p))
  if r.status_code==200:
   for src in re.findall(r'<script[^>]+src=["\']([^"\']+)',r.text,re.I):script_owners.setdefault(urljoin(r.url,src),set()).add(p)
 except Exception as e:page_results.append({'requested':p,'error':repr(e)})
def one(u):
 try:return {'url':u,'r':fetch(u,18)}
 except Exception as e:return {'url':u,'error':repr(e)}
interesting=[];errors=[];cands=set();contexts=[]
with ThreadPoolExecutor(max_workers=10) as ex:
 for fut in as_completed([ex.submit(one,u) for u in script_owners]):
  x=fut.result()
  if x.get('error'):errors.append({'requested':x['url'],'error':x['error']});continue
  r=x['r'];t=r.text;m=meta(r,x['url']);m['declared_by']=sorted(script_owners[x['url']])
  for v in re.findall(r'https?://[^"\'\\\s<>]+',t):
   if any(k in v.lower() for k in ['api','fantasy','bundesliga','dfl']):cands.add(v[:500])
  for v in re.findall(r'["\'](/(?:api|v1|v2|fantasy|players?|clubs?|teams?|fixtures?|matchdays?|gameweeks?|stats|ranking)[^"\']*)["\']',t,re.I):cands.add(v)
  if any(k in t.lower() for k in ['fantasy','player','market value','api','graphql']):
   for needle in ['fantasy','api','graphql','baseurl','player','marketvalue','lastseason','pointsLastSeason']:
    for z in list(re.finditer(needle,t,re.I))[:20]:contexts.append({'url':r.url,'needle':needle,'text':t[max(0,z.start()-700):min(len(t),z.start()+1500)]})
   interesting.append(m)
res={'schema':'NEXUS_BUNDESLIGA_OFFICIAL_FANTASY_PUBLIC_PROBE_V1','capture_started':now(),'pages':page_results,'script_count':len(script_owners),'interesting_scripts':interesting,'script_errors':errors,'api_candidates':sorted(cands)[:2000],'contexts':contexts[:500],'governance':{'authenticated_surface_accessed':False,'private_routes_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'pages':[(x.get('url'),x.get('status'),x.get('bytes')) for x in page_results],'scripts':len(script_owners),'interesting':len(interesting),'errors':len(errors),'api_candidates':sorted(cands)[:120]},ensure_ascii=False,indent=2))
