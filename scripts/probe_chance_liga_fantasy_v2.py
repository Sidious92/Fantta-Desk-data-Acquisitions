#!/usr/bin/env python3
import json,re,hashlib
from urllib.parse import urljoin
from pathlib import Path
import requests
BASE='https://fantasy.chanceliga.cz/'
OUT=Path('/mnt/data/nexus-chance-liga-fantasy-probe-v2'); OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition'})
def probe(url):
 r=s.get(url,timeout=30,allow_redirects=True); b=r.content
 x={'requested':url,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'preview':r.text[:1000]}
 try:
  j=r.json(); x['json_type']=type(j).__name__; x['json_keys']=list(j)[:50] if isinstance(j,dict) else None; x['json_len']=len(j) if hasattr(j,'__len__') else None
 except Exception: pass
 return r,x
res={'schema':'NEXUS_CHANCE_LIGA_FANTASY_PUBLIC_PROBE_V2','base':BASE,'tests':[],'scripts':[]}
for p in ['', 'api/bootstrap-static/','api/fixtures/','api/event/1/live/','api/element-summary/1/','player-list']:
 try:r,x=probe(urljoin(BASE,p));res['tests'].append(x);home=r.text if p=='' else locals().get('home','')
 except Exception as e:res['tests'].append({'requested':urljoin(BASE,p),'error':repr(e)})
# scripts from home
try:
 r,_=probe(BASE); html=r.text
 for src in re.findall(r'<script[^>]+src=[\"\']([^\"\']+)',html,re.I):
  u=urljoin(BASE,src)
  try:
   rr,x=probe(u); txt=rr.text
   x['contexts']={k:[txt[max(0,m.start()-100):m.end()+220] for m in list(re.finditer(k,txt,re.I))[:8]] for k in ['bootstrap-static','element-summary','/api/','fixtures']}
   res['scripts'].append(x)
  except Exception as e:res['scripts'].append({'requested':u,'error':repr(e)})
except Exception: pass
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps([(x.get('requested'),x.get('status'),x.get('json_keys')) for x in res['tests']],indent=2))
