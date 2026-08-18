#!/usr/bin/env python3
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
BASE='https://ligue1.com/en/fantasy'
OUT=Path('/mnt/data/nexus-ligue1-official-fantasy-probe-v1');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/json,*/*'})
def rec(r,u):
 b=r.content;x={'requested':u,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'preview':r.text[:1200]}
 try:
  j=r.json();x['json_type']=type(j).__name__;x['json_keys']=list(j)[:80] if isinstance(j,dict) else None;x['json_len']=len(j) if hasattr(j,'__len__') else None
 except Exception:pass
 return x
r=s.get(BASE,timeout=40,allow_redirects=True);r.raise_for_status();html=r.text
res={'schema':'NEXUS_LIGUE1_OFFICIAL_FANTASY_PUBLIC_PROBE_V1','page':rec(r,BASE),'scripts':[],'api_candidates':[],'literal_tests':[]}
urls=[]
for src in re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I):urls.append(urljoin(r.url,src))
api=set()
for u in dict.fromkeys(urls):
 try:
  rr=s.get(u,timeout=40);txt=rr.text;x=rec(rr,u)
  for pat in [r'["\']([^"\']{1,300}(?:api|fantasy|player|rating|team|gameweek|round)[^"\']{0,200})["\']']:
   for m in re.findall(pat,txt,re.I):
    if not m.startswith('data:'):api.add(m)
  x['contexts']={k:[txt[max(0,m.start()-150):m.end()+350] for m in list(re.finditer(k,txt,re.I))[:12]] for k in ['api','fantasy','player','rating','gameweek']}
  res['scripts'].append(x)
 except Exception as e:res['scripts'].append({'requested':u,'error':repr(e)})
res['api_candidates']=sorted(api)[:1000]
# Only conservative anonymous read probes suggested by common app structure.
for p in ['/api/fantasy','/api/fantasy/players','/api/fantasy/teams','/api/players','/api/v1/fantasy','/api/v1/players','/en/fantasy/players']:
 u=urljoin('https://ligue1.com',p)
 try:
  rr=s.get(u,timeout=30,allow_redirects=True);res['literal_tests'].append(rec(rr,u))
 except Exception as e:res['literal_tests'].append({'requested':u,'error':repr(e)})
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'page':res['page']['status'],'scripts':len(res['scripts']),'api_candidates':len(res['api_candidates']),'tests':[(x.get('requested'),x.get('status')) for x in res['literal_tests']]},indent=2))
