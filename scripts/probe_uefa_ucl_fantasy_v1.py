#!/usr/bin/env python3
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
BASE='https://gaming.uefa.com/en/uclfantasy/fantasy-landing/'
OUT=Path('/mnt/data/nexus-uefa-ucl-fantasy-probe-v1');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/json,*/*'})
def meta(r,u):
 b=r.content;x={'requested':u,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'preview':r.text[:1200]}
 try:
  j=r.json();x['json_type']=type(j).__name__;x['json_keys']=list(j)[:80] if isinstance(j,dict) else None;x['json_len']=len(j) if hasattr(j,'__len__') else None
 except Exception:pass
 return x
r=s.get(BASE,timeout=40,allow_redirects=True);r.raise_for_status();html=r.text
scripts=[];cands=set();interesting=[]
for src in dict.fromkeys(re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I)):
 u=urljoin(r.url,src)
 try:
  rr=s.get(u,timeout=40);txt=rr.text;x=meta(rr,u)
  for pat in [r'["\'](https?://[^"\']{1,300})["\']',r'["\'](\/[A-Za-z0-9][A-Za-z0-9_./?=&:${}-]{2,200})["\']']:
   for v in re.findall(pat,txt):
    lv=v.lower()
    if any(k in lv for k in ['api','fantasy','player','squad','fixture','matchday','gameweek','ucl','gaming']):cands.add(v)
  if any(k in txt.lower() for k in ['fantasy','player','gameweek','matchday','api']):
   x['contexts']={k:[txt[max(0,m.start()-160):m.end()+350] for m in list(re.finditer(k,txt,re.I))[:15]] for k in ['api','fantasy','player','gameweek','matchday','baseurl','graphql']}
   interesting.append(x)
 except Exception as e:scripts.append({'requested':u,'error':repr(e)})
res={'schema':'NEXUS_UEFA_UCL_FANTASY_PUBLIC_PROBE_V1','page':meta(r,BASE),'interesting_scripts':interesting,'script_errors':scripts,'api_candidates':sorted(cands)[:1500]}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'page':res['page']['status'],'interesting_scripts':len(interesting),'api_candidates':len(cands)},indent=2))
