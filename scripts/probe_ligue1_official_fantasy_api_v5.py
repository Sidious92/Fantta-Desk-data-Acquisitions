#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
SITE='https://ligue1.com/en/fantasy'
OUT=Path('/mnt/data/nexus-ligue1-official-fantasy-api-probe-v5');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/javascript,*/*'})
def sha(b):return hashlib.sha256(b).hexdigest()
r=s.get(SITE,timeout=40);r.raise_for_status();html=r.text
urls=set(urljoin(r.url,x) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I))
# Add all fantasy page chunks from the build manifest.
manifest=next((u for u in urls if '_buildManifest.js' in u),None)
if not manifest:
 m=re.search(r'/_next/static/([^/]+)/',html)
 if m:manifest=urljoin(r.url,f'/_next/static/{m.group(1)}/_buildManifest.js')
if manifest:
 mr=s.get(manifest,timeout=40);mr.raise_for_status();mt=mr.text
 for m in re.finditer(r'["\'](/fantasy[^"\']*)["\']\s*:\s*\[([^\]]*)\]',mt):
  for c in re.findall(r'["\']([^"\']+\.js)["\']',m.group(2)):
   urls.add(urljoin(r.url,'/_next/'+c if c.startswith('static/') else c))
needles=['apiFantasyClient','L1_FANTASY_API_URL','api.mpg.football/fantasy']
hits=[];errors=[]
for u in sorted(urls):
 try:
  rr=s.get(u,timeout=45);rr.raise_for_status();t=rr.text
  positions=[]
  for needle in needles:
   positions.extend((needle,m.start()) for m in re.finditer(re.escape(needle),t))
  if not positions:continue
  contexts=[]
  for needle,pos in sorted(positions,key=lambda x:x[1])[:100]:
   start=max(0,pos-1800);end=min(len(t),pos+4000);ctx=t[start:end]
   contexts.append({'needle':needle,'offset':pos,'text':ctx,'string_literals':sorted(set(re.findall(r'["\']([^"\']{1,180})["\']',ctx)))[:250]})
  hits.append({'url':rr.url,'bytes':len(rr.content),'sha256':sha(rr.content),'contexts':contexts})
 except Exception as e:errors.append({'url':u,'error':repr(e)})
res={'schema':'NEXUS_LIGUE1_OFFICIAL_FANTASY_API_PUBLIC_PROBE_V5','site':SITE,'scanned_urls':len(urls),'hit_files':len(hits),'hits':hits,'errors':errors,'governance':{'network_calls_limited_to_frontend_assets':True,'api_endpoint_requests_made':False,'authenticated_surface_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'scanned':len(urls),'hit_files':len(hits),'contexts':sum(len(x['contexts']) for x in hits)},indent=2))
