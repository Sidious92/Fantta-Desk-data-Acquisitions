#!/usr/bin/env python3
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
SITE='https://ligue1.com/en/fantasy'
FBASE='https://api.mpg.football/fantasy'
OUT=Path('/mnt/data/nexus-ligue1-official-fantasy-api-probe-v3');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*','Origin':'https://ligue1.com','Referer':SITE})

def meta(r,u):
 b=r.content;x={'requested':u,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'preview':r.text[:1200]}
 try:
  j=r.json();x['json_type']=type(j).__name__;x['json_keys']=list(j)[:80] if isinstance(j,dict) else None;x['json_len']=len(j) if hasattr(j,'__len__') else None
 except Exception:pass
 return x

r=s.get(SITE,timeout=40);r.raise_for_status();html=r.text
scripts=[]; candidates=set();interesting=[]
for src in dict.fromkeys(re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I)):
 u=urljoin(r.url,src)
 try:
  rr=s.get(u,timeout=40);txt=rr.text
  # A chunk is interesting if it references the shared api-client module or explicit fantasy config/routes.
  is_interesting=('820203' in txt or 'apiFantasyClient' in txt or 'L1_FANTASY_API_URL' in txt or '/fantasy' in txt)
  if is_interesting:
   p=OUT/('chunk-'+hashlib.sha1(u.encode()).hexdigest()+'.js');p.write_text(txt,encoding='utf-8')
   interesting.append({'url':u,'bytes':len(rr.content),'sha256':hashlib.sha256(rr.content).hexdigest(),'local_path':p.name})
   # Literal slash routes in quoted strings and simple template-prefixes.
   for pat in [r'["\'](\/[A-Za-z0-9][A-Za-z0-9_./?=&:-]{1,120})["\']',r'`(\/[A-Za-z0-9][A-Za-z0-9_./?=&:-]{1,120})`']:
    for v in re.findall(pat,txt):
     candidates.add(v)
 except Exception as e:
  scripts.append({'url':u,'error':repr(e)})

# Keep plausible fantasy-backend paths. Remove known website/auth/static routes and dynamic-template fragments.
blocked_prefixes=('/api/auth','/_next','/fonts','/images','/videos','/articles','/competitions','/club-sheet','/player-sheet','/match-sheet','/menu','/debug-mode','/fantasy')
blocked_exact={'/','/en','/fr','/es','/login','/accessibility','/contact-us','/broadcasters','/international-broadcasters'}
plausible=[]
for v in sorted(candidates):
 if v in blocked_exact or v.startswith(blocked_prefixes):continue
 if '${' in v or '<' in v or '>' in v:continue
 if len(v)>100:continue
 plausible.append(v)
# Always include verified /rules and route-like nouns seen in fantasy code.
for v in ['/rules']:
 if v not in plausible:plausible.append(v)

tests=[]
for path in plausible[:180]:
 u=FBASE+path
 try:
  rr=s.get(u,timeout=20,allow_redirects=True);tests.append(meta(rr,u))
 except Exception as e:tests.append({'requested':u,'path':path,'error':repr(e)})

res={'schema':'NEXUS_LIGUE1_OFFICIAL_FANTASY_API_PUBLIC_PROBE_V3','site':SITE,'fantasy_api_base':FBASE,'interesting_chunks':interesting,'candidate_count':len(candidates),'plausible_candidates':plausible,'tests':tests,'non_404_tests':[x for x in tests if x.get('status') not in (404,None)]}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'interesting_chunks':len(interesting),'candidates':len(candidates),'plausible':len(plausible),'non404':[(x.get('url'),x.get('status'),x.get('json_keys')) for x in res['non_404_tests']]},indent=2))
