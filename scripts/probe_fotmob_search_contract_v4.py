#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from urllib.parse import urljoin
import requests
PAGE='https://www.fotmob.com/players/1190371/matija-frigan'
OUT=Path('/mnt/data/nexus-fotmob-search-contract-v4');OUT.mkdir(parents=True,exist_ok=True)
H={'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/javascript,*/*'}
def sha(b):return hashlib.sha256(b).hexdigest()
def fetch(u,timeout=25):return requests.get(u,headers=H,timeout=(8,timeout),allow_redirects=True)
r=fetch(PAGE);r.raise_for_status();html=r.text
srcs=list(dict.fromkeys(urljoin(r.url,x) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I)))
def one(u):
 try:
  rr=fetch(u,20);return {'url':u,'r':rr}
 except Exception as e:return {'url':u,'error':repr(e)}
hits=[];errors=[]
with ThreadPoolExecutor(max_workers=8) as ex:
 for fut in as_completed([ex.submit(one,u) for u in srcs]):
  x=fut.result()
  if x.get('error'):errors.append({'url':x['url'],'error':x['error']});continue
  rr=x['r'];t=rr.text
  if 'html' in rr.headers.get('content-type','').lower():continue
  contexts=[]
  for needle in ['searchapi','search/suggest','suggest','autocomplete','searchTerm','searchQuery','/search','search?','searchResults']:
   for m in list(re.finditer(re.escape(needle),t,re.I))[:80]:
    ctx=t[max(0,m.start()-1800):min(len(t),m.start()+4200)]
    literals=sorted(set(re.findall(r'["\']([^"\']{1,300})["\']',ctx)))
    templates=sorted(set(re.findall(r'`([^`]{1,300})`',ctx)))
    apiish=[z for z in literals+templates if any(k in z.lower() for k in ['search','suggest','api','query','term','player'])]
    contexts.append({'needle':needle,'offset':m.start(),'apiish':apiish[:200],'context':ctx})
  if contexts:hits.append({'url':rr.url,'bytes':len(rr.content),'sha256':sha(rr.content),'contexts':contexts})
res={'schema':'NEXUS_FOTMOB_PUBLIC_SEARCH_CONTRACT_PROBE_V4','page':{'url':r.url,'status':r.status_code,'bytes':len(r.content),'sha256':sha(r.content)},'declared_script_count':len(srcs),'hit_files':len(hits),'hits':hits,'errors':errors,'governance':{'only_public_page_declared_assets_requested':True,'search_endpoint_requests_made':False,'authenticated_surface_accessed':False,'private_routes_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'scripts':len(srcs),'hit_files':len(hits),'contexts':sum(len(x['contexts']) for x in hits),'compact':[{'url':x['url'],'contexts':[{'needle':c['needle'],'apiish':c['apiish'][:20]} for c in x['contexts'][:20]]} for x in hits[:20]]},ensure_ascii=False,indent=2))
