#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin
import requests
BASE='https://gaming.uefa.com/en/uclfantasy/fantasy-landing/'
OUT=Path('/mnt/data/nexus-uefa-ucl-fantasy-probe-v2');OUT.mkdir(parents=True,exist_ok=True)
HEADERS={'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/json,*/*'}
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def meta(r,u):
 b=r.content;x={'requested':u,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':sha(b),'preview':r.text[:1200]}
 try:
  j=r.json();x['json_type']=type(j).__name__;x['json_keys']=list(j)[:80] if isinstance(j,dict) else None;x['json_len']=len(j) if hasattr(j,'__len__') else None
 except Exception:pass
 return x
def get(url,timeout=20,attempts=2):
 last=None
 for i in range(attempts):
  try:
   r=requests.get(url,headers=HEADERS,timeout=timeout,allow_redirects=True)
   r.raise_for_status();return r
  except Exception as e:last=e;time.sleep(.4*(i+1))
 raise last or RuntimeError(url)
def dump_progress(o):
 (OUT/'PROGRESS.json').write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
started=now();page=get(BASE,timeout=25);html=page.text
script_urls=list(dict.fromkeys(urljoin(page.url,src) for src in re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I)))
progress={'schema':'NEXUS_UEFA_UCL_FANTASY_PUBLIC_PROBE_V2_PROGRESS','started':started,'page':meta(page,BASE),'script_count':len(script_urls),'completed':0,'errors':0};dump_progress(progress)
def one(u):
 try:
  r=get(u,timeout=18,attempts=2);return {'url':u,'response':r}
 except Exception as e:return {'url':u,'error':repr(e)}
interesting=[];errors=[];cands=set();completed=0
with ThreadPoolExecutor(max_workers=10) as ex:
 futs=[ex.submit(one,u) for u in script_urls]
 for fut in as_completed(futs):
  x=fut.result();completed+=1
  if x.get('error'):
   errors.append({'requested':x['url'],'error':x['error']})
  else:
   rr=x['response'];txt=rr.text;m=meta(rr,x['url'])
   for pat in [r'["\'](https?://[^"\']{1,300})["\']',r'["\'](\/[A-Za-z0-9][A-Za-z0-9_./?=&:${}-]{2,200})["\']']:
    for v in re.findall(pat,txt):
     lv=v.lower()
     if any(k in lv for k in ['api','fantasy','player','squad','fixture','matchday','gameweek','ucl','gaming']):cands.add(v)
   if any(k in txt.lower() for k in ['fantasy','player','gameweek','matchday','api']):
    m['contexts']={k:[txt[max(0,z.start()-160):z.end()+350] for z in list(re.finditer(k,txt,re.I))[:15]] for k in ['api','fantasy','player','gameweek','matchday','baseurl','graphql']}
    interesting.append(m)
  if completed%10==0 or completed==len(script_urls):
   progress.update({'completed':completed,'errors':len(errors),'interesting_scripts':len(interesting),'candidate_count':len(cands),'updated':now()});dump_progress(progress)
res={'schema':'NEXUS_UEFA_UCL_FANTASY_PUBLIC_PROBE_V2','execution_profile':'BOUNDED_CONCURRENT_RETRY_OF_V1','capture_started':started,'capture_completed':now(),'page':meta(page,BASE),'script_count':len(script_urls),'scripts_completed':completed,'interesting_scripts':interesting,'script_errors':errors,'api_candidates':sorted(cands)[:1500],'governance':{'same_v1_landing_page':True,'same_v1_script_discovery':True,'authenticated_surface_accessed':False,'private_routes_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'page':res['page']['status'],'scripts':len(script_urls),'completed':completed,'errors':len(errors),'interesting_scripts':len(interesting),'api_candidates':len(cands)},indent=2))
