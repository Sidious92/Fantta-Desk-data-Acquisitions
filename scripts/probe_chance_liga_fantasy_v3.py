#!/usr/bin/env python3
import json,re,hashlib
from pathlib import Path
import requests

BASE='https://fantasy.chanceliga.cz'
BUNDLE=BASE+'/assets/index-BemiCAop.js'
OUT=Path('/mnt/data/nexus-chance-liga-fantasy-probe-v3'); OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*'})

def meta(r,requested):
 b=r.content
 x={'requested':requested,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'preview':r.text[:1000]}
 try:
  j=r.json();x['json_type']=type(j).__name__;x['json_keys']=list(j)[:60] if isinstance(j,dict) else None;x['json_len']=len(j) if hasattr(j,'__len__') else None
 except Exception: pass
 return x

r=s.get(BUNDLE,timeout=40); r.raise_for_status(); txt=r.text
cands=set()
# Direct GET factory calls.
for m in re.finditer(r'qt\(\"([^\"]+)\"\)',txt): cands.add(m.group(1))
for m in re.finditer(r"qt\('([^']+)'\)",txt): cands.add(m.group(1))
# Route-looking string constants. Keep only football/fantasy read domains.
keywords=('season','player','team','club','round','match','fixture','stat','leader','ranking','position','squad','transfer','market','gameweek','calendar')
for m in re.finditer(r'[\"\']([A-Za-z0-9_{}./?-]{3,120})[\"\']',txt):
 v=m.group(1)
 lv=v.lower()
 if any(k in lv for k in keywords) and '/' in v and not v.startswith(('http','assets','static')):
  cands.add(v)
# Explicit known route.
cands.add('seasons/active')
# Exclude obvious authenticated/private/write-oriented routes and placeholders we cannot safely resolve.
blocked=('session','auth','login','register','password','user/','users/','my-team','myteam','league/','leagues/','transfer','market','watchlist','favorite','draft','admin')
safe=[]
for v in sorted(cands):
 lv=v.lower().strip('/')
 if not lv or any(b in lv for b in blocked): continue
 if any(x in v for x in ('${','`','<','>')): continue
 if len(v)>120: continue
 safe.append(v.strip('/'))
# Limit to a bounded set, but preserve all discovered in output.
tests=[]
for path in safe[:120]:
 url=f'{BASE}/api/v1/{path}'
 try:
  rr=s.get(url,timeout=25,allow_redirects=True)
  tests.append(meta(rr,url))
 except Exception as e: tests.append({'requested':url,'error':repr(e)})

# Context for every candidate that looks especially useful.
contexts={}
for key in ['seasons/active','players','player','stats','statistics','teams','rounds','matches']:
 contexts[key]=[txt[max(0,m.start()-220):m.end()+500] for m in list(re.finditer(re.escape(key),txt,re.I))[:20]]
res={'schema':'NEXUS_CHANCE_LIGA_FANTASY_PUBLIC_PROBE_V3','bundle':meta(r,BUNDLE),'candidates_all':sorted(cands),'safe_candidates':safe,'tests':tests,'contexts':contexts}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'candidates':len(cands),'safe':len(safe),'http200':[x['requested'] for x in tests if x.get('status')==200],'http401':[x['requested'] for x in tests if x.get('status')==401],'http403':[x['requested'] for x in tests if x.get('status')==403]},indent=2))
