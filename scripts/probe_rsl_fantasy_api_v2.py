#!/usr/bin/env python3
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
SITE='https://fantasy.spl.com.sa/'
OUT=Path('/mnt/data/nexus-rsl-fantasy-api-probe-v2');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*','Referer':SITE})
def meta(r,u):
 b=r.content;x={'requested':u,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'preview':r.text[:1600]}
 try:
  j=r.json();x['json_type']=type(j).__name__;x['json_keys']=list(j)[:100] if isinstance(j,dict) else None;x['json_len']=len(j) if hasattr(j,'__len__') else None
 except Exception:pass
 return x
r=s.get(SITE,timeout=30);r.raise_for_status();html=r.text
scripts=[urljoin(r.url,x) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I)]
main=None
for u in scripts:
 try:
  rr=s.get(u,timeout=40)
  if 'fantasy.spl.com.sa/assets/index-' in u:
   main=(u,rr.text,rr.content);break
 except Exception:pass
if main is None:raise SystemExit('main bundle not found')
u,txt,b=main
contexts={k:[txt[max(0,m.start()-400):m.end()+800] for m in list(re.finditer(re.escape(k),txt,re.I))[:50]] for k in ['/api/','api/player','total_points','news_added','fetch(','axios','baseURL']}
strings=set()
for m in re.findall(r'["\']([^"\']{1,180})["\']',txt):
 lm=m.lower()
 if any(k in lm for k in ['player','fixture','event','team','club','statistic','status','gameweek','round','dream-team']) and ('/' in m or m.isidentifier()):strings.add(m)
# Conservative guessed reads against same-origin /api/ only; no auth/session/user endpoints.
paths=['api/','api/status/','api/settings/','api/config/','api/players/','api/player-list/','api/statistics/','api/teams/','api/clubs/','api/events/','api/gameweeks/','api/rounds/','api/fixtures/','api/dream-team/','api/players?sort=total_points','api/players/?sort=total_points','api/players/?filter=all&sort=news_added&search=']
tests=[]
for p in paths:
 url=urljoin(SITE,p)
 try:
  rr=s.get(url,timeout=25,allow_redirects=True);tests.append(meta(rr,url))
 except Exception as e:tests.append({'requested':url,'error':repr(e)})
res={'schema':'NEXUS_RSL_FANTASY_API_PUBLIC_PROBE_V2','site':SITE,'main_bundle':{'url':u,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()},'contexts':contexts,'candidate_strings':sorted(strings)[:2000],'tests':tests,'non_404_tests':[x for x in tests if x.get('status') not in (404,None)]}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'bundle':u,'candidate_strings':len(strings),'non404':[(x.get('url'),x.get('status'),x.get('json_keys')) for x in res['non_404_tests']]},indent=2))
