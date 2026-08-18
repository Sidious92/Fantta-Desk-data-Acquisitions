#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
SITE='https://ligue1.com/en/fantasy'
API='https://api.mpg.football/fantasy'
OUT=Path('/mnt/data/nexus-ligue1-official-fantasy-api-probe-v4');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*','Referer':SITE})
def sha(b):return hashlib.sha256(b).hexdigest()
def meta(r):
 b=r.content;x={'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':sha(b),'preview':r.text[:1000]}
 try:
  o=r.json();x['json_type']=type(o).__name__;x['json_keys']=list(o)[:80] if isinstance(o,dict) else None;x['json_len']=len(o) if hasattr(o,'__len__') else None
 except Exception:pass
 return x
page=s.get(SITE,timeout=40);page.raise_for_status();html=page.text
script_urls=[urljoin(page.url,x) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I)]
manifest_url=next((u for u in script_urls if '_buildManifest.js' in u),None)
if not manifest_url:
 # derive build id from any /_next/static/<buildid>/ script if Next omits manifest tag
 m=re.search(r'/_next/static/([^/]+)/',html)
 if m:manifest_url=urljoin(page.url,f'/_next/static/{m.group(1)}/_buildManifest.js')
if not manifest_url:raise SystemExit('build manifest not found')
mr=s.get(manifest_url,timeout=40);mr.raise_for_status();mt=mr.text
# Download only chunks referenced in proximity to fantasy routes, plus all chunks whose names are directly listed in route manifest blocks.
route_chunks=set()
for m in re.finditer(r'["\'](/fantasy[^"\']*)["\']\s*:\s*\[([^\]]*)\]',mt):
 route=m.group(1);body=m.group(2)
 for c in re.findall(r'["\']([^"\']+\.js)["\']',body):route_chunks.add((route,urljoin(manifest_url,c if c.startswith('/') else '/_next/'+c if c.startswith('static/') else c)))
# fallback: inspect contexts around every /fantasy mention for static chunks
for m in re.finditer(r'/fantasy',mt):
 ctx=mt[max(0,m.start()-500):m.end()+1500]
 for c in re.findall(r'["\']([^"\']*static/chunks/[^"\']+\.js)["\']',ctx):route_chunks.add(('manifest-context',urljoin(page.url,'/_next/'+c if not c.startswith('/') else c)))
chunks=[];literal_gets=set();template_gets=set();all_strings=set()
for route,u in sorted(route_chunks):
 try:
  r=s.get(u,timeout=40);r.raise_for_status();t=r.text
  if 'apiFantasyClient' not in t and 'L1_FANTASY_API_URL' not in t and '/fantasy' not in t:continue
  lp=OUT/('chunk-'+sha(r.content)[:16]+'.js');lp.write_bytes(r.content)
  for pat in [r'apiFantasyClient\.get\(["\']([^"\']+)["\']',r'\.get\(["\']([^"\']+)["\']']:
   for x in re.findall(pat,t):
    if x.startswith('/'):literal_gets.add(x)
  for x in re.findall(r'apiFantasyClient\.get\(`([^`]+)`',t):template_gets.add(x)
  # Generic literal route inventory from fantasy-specific chunks; later tests are restricted to plausible provider routes.
  for x in re.findall(r'["\'](/[-A-Za-z0-9_./?=&]+)["\']',t):all_strings.add(x)
  chunks.append({'route':route,'url':r.url,'bytes':len(r.content),'sha256':sha(r.content),'local_path':str(lp.name)})
 except Exception as e:chunks.append({'route':route,'url':u,'error':repr(e)})
# Include already verified public endpoints and candidate literals that look like fantasy API resources, excluding web page/auth routes.
candidates=set(['/rules','/championships-settings'])|literal_gets
for x in all_strings:
 lx=x.lower()
 if any(k in lx for k in ['championship','player','club','gameweek','ranking','fantasy','asset','season','team']) and not any(k in lx for k in ['/api/auth','/profile','/login','/fantasy/']):candidates.add(x)
tests=[]
for path in sorted(candidates):
 if '${' in path or ':' in path:continue
 try:
  r=s.get(API+path,timeout=35,allow_redirects=True);tests.append({'path':path,**meta(r)})
 except Exception as e:tests.append({'path':path,'error':repr(e)})
res={'schema':'NEXUS_LIGUE1_OFFICIAL_FANTASY_API_PUBLIC_PROBE_V4','site':SITE,'api_base':API,'build_manifest':meta(mr),'route_chunks':chunks,'literal_gets':sorted(literal_gets),'template_gets':sorted(template_gets),'candidate_count':len(candidates),'tests':tests,'non_404_tests':[x for x in tests if x.get('status') not in (None,404)],'governance':{'authenticated_surface_accessed':False,'bruteforce_endpoint_dictionary_used':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'chunks':len(chunks),'literal_gets':len(literal_gets),'tests':len(tests),'non404':[(x.get('path'),x.get('status')) for x in res['non_404_tests']]},ensure_ascii=False,indent=2))
