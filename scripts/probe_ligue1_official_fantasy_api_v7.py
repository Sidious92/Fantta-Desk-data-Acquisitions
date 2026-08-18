#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
ORIGIN='https://ligue1.com'
PAGES=['/en/fantasy','/en/fantasy/mercato','/en/fantasy/ranking','/en/fantasy/rules','/en/fantasy/captain','/en/fantasy/line-up','/en/fantasy/my-team']
OUT=Path('/mnt/data/nexus-ligue1-official-fantasy-api-probe-v7');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/javascript,*/*'})
def sha(b):return hashlib.sha256(b).hexdigest()
page_meta=[];owners={};errors=[]
for p in PAGES:
 try:
  r=s.get(ORIGIN+p,timeout=40,allow_redirects=True);b=r.content
  page_meta.append({'path':p,'url':r.url,'status':r.status_code,'bytes':len(b),'sha256':sha(b)})
  if r.status_code!=200:continue
  for src in re.findall(r'<script[^>]+src=["\']([^"\']+)',r.text,re.I):owners.setdefault(urljoin(r.url,src),set()).add(p)
 except Exception as e:errors.append({'page':p,'error':repr(e)})
hits=[]
for u,pages in sorted(owners.items()):
 try:
  r=s.get(u,timeout=45);r.raise_for_status();t=r.text
  if 'apiFantasyClient' not in t and '820203' not in t:continue
  contexts=[]
  for needle in ['apiFantasyClient','820203']:
   for m in list(re.finditer(re.escape(needle),t))[:80]:
    ctx=t[max(0,m.start()-5000):min(len(t),m.start()+12000)]
    literals=sorted(set(re.findall(r'["\']([^"\']{1,260})["\']',ctx)))
    templates=sorted(set(re.findall(r'`([^`]{1,260})`',ctx)))
    contexts.append({'needle':needle,'offset':m.start(),'text':ctx,'route_like_literals':[x for x in literals if x.startswith('/') or any(k in x.lower() for k in ['championship','player','club','gameweek','ranking','season','fantasy'])][:500],'templates':templates[:300]})
  hits.append({'url':r.url,'pages':sorted(pages),'bytes':len(r.content),'sha256':sha(r.content),'contexts':contexts})
 except Exception as e:errors.append({'script':u,'error':repr(e)})
res={'schema':'NEXUS_LIGUE1_OFFICIAL_FANTASY_API_PUBLIC_PROBE_V7','pages':page_meta,'unique_scripts':len(owners),'hit_files':len(hits),'hits':hits,'errors':errors,'governance':{'network_calls_limited_to_public_ligue1_pages_and_their_declared_assets':True,'fantasy_api_endpoint_requests_made':False,'authenticated_surface_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'pages':page_meta,'unique_scripts':len(owners),'hit_files':len(hits),'contexts':sum(len(x['contexts']) for x in hits)},ensure_ascii=False,indent=2))
