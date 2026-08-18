#!/usr/bin/env python3
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
BASE='https://fantasy.spl.com.sa/'
OUT=Path('/mnt/data/nexus-rsl-fantasy-probe-v1');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/json,*/*'})
def meta(r,u):
 b=r.content;x={'requested':u,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'preview':r.text[:1200]}
 try:
  j=r.json();x['json_type']=type(j).__name__;x['json_keys']=list(j)[:80] if isinstance(j,dict) else None;x['json_len']=len(j) if hasattr(j,'__len__') else None
 except Exception:pass
 return x
pages={};html=''
for name,path in [('home',''),('player_list','player-list'),('statistics','statistics')]:
 try:
  r=s.get(urljoin(BASE,path),timeout=40,allow_redirects=True);pages[name]=meta(r,urljoin(BASE,path));
  if name=='player_list':html=r.text
 except Exception as e:pages[name]={'error':repr(e)}
scripts=[];cands=set()
for src in dict.fromkeys(re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I)):
 u=urljoin(BASE,src)
 try:
  rr=s.get(u,timeout=40);txt=rr.text;x=meta(rr,u)
  for pat in [r'["\'](https?://[^"\']{1,300})["\']',r'["\'](\/[A-Za-z0-9][A-Za-z0-9_./?=&:${}-]{2,180})["\']']:
   for v in re.findall(pat,txt):
    lv=v.lower()
    if any(k in lv for k in ['api','player','stat','team','club','round','week','fixture','fantasy']):cands.add(v)
  x['contexts']={k:[txt[max(0,m.start()-140):m.end()+300] for m in list(re.finditer(k,txt,re.I))[:12]] for k in ['api','player','statistics','baseurl','axios','graphql']}
  scripts.append(x)
 except Exception as e:scripts.append({'requested':u,'error':repr(e)})
res={'schema':'NEXUS_RSL_FANTASY_PUBLIC_PROBE_V1','pages':pages,'scripts':scripts,'api_candidates':sorted(cands)[:1200]}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'pages':{k:v.get('status') for k,v in pages.items()},'scripts':len(scripts),'api_candidates':len(cands)},indent=2))
