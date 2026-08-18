#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
LANDINGS=[
 'https://gaming.uefa.com/en/uclfantasy/fantasy-landing',
 'https://gaming.uefa.com/it/uclfantasy/fantasy-landing'
]
OUT=Path('/mnt/data/nexus-uefa-ucl-fantasy-probe-v2-1');OUT.mkdir(parents=True,exist_ok=True)
HEADERS={'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/json,*/*'}
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def meta(r,u):
 b=r.content;x={'requested':u,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':sha(b),'preview':r.text[:1200]}
 try:
  j=r.json();x['json_type']=type(j).__name__;x['json_keys']=list(j)[:80] if isinstance(j,dict) else None;x['json_len']=len(j) if hasattr(j,'__len__') else None
 except Exception:pass
 return x
def fetch(u,timeout=15):return requests.get(u,headers=HEADERS,timeout=(8,timeout),allow_redirects=True)
def dump(name,o):(OUT/name).write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
started=now();landing_attempts=[];page=None;chosen=None
for u in LANDINGS:
 try:
  r=fetch(u,12);landing_attempts.append({'url':u,'status':r.status_code,'final_url':r.url,'bytes':len(r.content)})
  if r.status_code==200 and len(r.content)>500:
   page=r;chosen=u;break
 except Exception as e:landing_attempts.append({'url':u,'error':repr(e)})
dump('PROGRESS.json',{'schema':'NEXUS_UEFA_UCL_FANTASY_PUBLIC_PROBE_V2_1_PROGRESS','started':started,'landing_attempts':landing_attempts,'chosen_landing':chosen})
if page is None:
 res={'schema':'NEXUS_UEFA_UCL_FANTASY_PUBLIC_PROBE_V2_1','status':'RUNNER_EGRESS_BLOCKED','capture_started':started,'capture_completed':now(),'landing_attempts':landing_attempts,'provider_conclusion':'NONE','notes':'GitHub-hosted runner could not retrieve either official UEFA Gaming locale landing. This is execution/network evidence, not a provider data-access verdict.','governance':{'authenticated_surface_accessed':False,'private_routes_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
 dump('RESULT.json',res);print(json.dumps(res,indent=2));raise SystemExit(0)
html=page.text;script_urls=list(dict.fromkeys(urljoin(page.url,x) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I)))
def one(u):
 try:
  r=fetch(u,15);return {'url':u,'r':r}
 except Exception as e:return {'url':u,'error':repr(e)}
interesting=[];errors=[];cands=set();done=0
with ThreadPoolExecutor(max_workers=10) as ex:
 for fut in as_completed([ex.submit(one,u) for u in script_urls]):
  x=fut.result();done+=1
  if x.get('error'):errors.append({'requested':x['url'],'error':x['error']});continue
  r=x['r'];txt=r.text;m=meta(r,x['url'])
  for pat in [r'["\'](https?://[^"\']{1,300})["\']',r'["\'](\/[A-Za-z0-9][A-Za-z0-9_./?=&:${}-]{2,200})["\']']:
   for v in re.findall(pat,txt):
    if any(k in v.lower() for k in ['api','fantasy','player','squad','fixture','matchday','gameweek','ucl','gaming']):cands.add(v)
  if any(k in txt.lower() for k in ['fantasy','player','gameweek','matchday','api']):
   m['contexts']={k:[txt[max(0,z.start()-160):z.end()+350] for z in list(re.finditer(k,txt,re.I))[:15]] for k in ['api','fantasy','player','gameweek','matchday','baseurl','graphql']};interesting.append(m)
res={'schema':'NEXUS_UEFA_UCL_FANTASY_PUBLIC_PROBE_V2_1','status':'CAPTURED','capture_started':started,'capture_completed':now(),'landing_attempts':landing_attempts,'chosen_landing':chosen,'page':meta(page,chosen),'script_count':len(script_urls),'scripts_completed':done,'interesting_scripts':interesting,'script_errors':errors,'api_candidates':sorted(cands)[:1500],'governance':{'official_locale_fallback_only':True,'authenticated_surface_accessed':False,'private_routes_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
dump('RESULT.json',res);print(json.dumps({'status':res['status'],'chosen':chosen,'scripts':len(script_urls),'completed':done,'errors':len(errors),'candidates':len(cands)},indent=2))
