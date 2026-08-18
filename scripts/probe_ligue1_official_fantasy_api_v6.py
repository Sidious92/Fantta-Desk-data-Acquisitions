#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
SITE='https://ligue1.com/en/fantasy'; CLIENT_MODULE='820203'
OUT=Path('/mnt/data/nexus-ligue1-official-fantasy-api-probe-v6');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/javascript,*/*'})
def sha(b):return hashlib.sha256(b).hexdigest()
r=s.get(SITE,timeout=40);r.raise_for_status();html=r.text
urls=set(urljoin(r.url,x) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I))
manifest=next((u for u in urls if '_buildManifest.js' in u),None)
if not manifest:
 m=re.search(r'/_next/static/([^/]+)/',html)
 if m:manifest=urljoin(r.url,f'/_next/static/{m.group(1)}/_buildManifest.js')
if manifest:
 mr=s.get(manifest,timeout=40);mr.raise_for_status();mt=mr.text
 # Scan every JS chunk named in the manifest, not guessed endpoints.
 for c in re.findall(r'["\']([^"\']*static/chunks/[^"\']+\.js)["\']',mt):
  urls.add(urljoin(r.url,'/_next/'+c if not c.startswith('/') else c))
hits=[];errors=[]
for u in sorted(urls):
 try:
  rr=s.get(u,timeout=45);rr.raise_for_status();t=rr.text
  positions=[m.start() for m in re.finditer(CLIENT_MODULE,t)]
  if not positions:continue
  contexts=[]
  for pos in positions[:100]:
   ctx=t[max(0,pos-3500):min(len(t),pos+9000)]
   literals=sorted(set(re.findall(r'["\']([^"\']{1,240})["\']',ctx)))
   path_literals=sorted(x for x in literals if x.startswith('/') or any(k in x.lower() for k in ['championship','player','club','gameweek','ranking','season','fantasy']))
   templates=sorted(set(re.findall(r'`([^`]{1,240})`',ctx)))
   contexts.append({'offset':pos,'text':ctx,'path_like_literals':path_literals[:400],'templates':templates[:200]})
  hits.append({'url':rr.url,'bytes':len(rr.content),'sha256':sha(rr.content),'contexts':contexts})
 except Exception as e:errors.append({'url':u,'error':repr(e)})
res={'schema':'NEXUS_LIGUE1_OFFICIAL_FANTASY_API_PUBLIC_PROBE_V6','site':SITE,'client_module':CLIENT_MODULE,'scanned_urls':len(urls),'hit_files':len(hits),'hits':hits,'errors':errors,'governance':{'network_calls_limited_to_frontend_assets':True,'api_endpoint_requests_made':False,'authenticated_surface_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'scanned':len(urls),'hit_files':len(hits),'contexts':sum(len(x['contexts']) for x in hits)},indent=2))
