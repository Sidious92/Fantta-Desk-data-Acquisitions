#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
import requests
URL='https://fantasy.slgr.gr/main.dart.js'
OUT=Path('/mnt/data/nexus-slgr-fantasy-public-probe-v2');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/javascript,text/javascript,*/*','Referer':'https://fantasy.slgr.gr/'})
def sha(b):return hashlib.sha256(b).hexdigest()
r=s.get(URL,timeout=90,allow_redirects=True);r.raise_for_status();b=r.content;t=r.text
# Keep exact bundle only in Actions artifact, not committed to repository status.
(OUT/'main.dart.js').write_bytes(b)
urls=sorted(set(x.rstrip('.,;') for x in re.findall(r'https?://[^"\'\\\s<>]+',t)))
interesting_urls=[u for u in urls if any(k in u.lower() for k in ['api','fantasy','slgr','funatix','league','firebase'])]
# Dart compiled strings are still visible; capture API-shaped and football-shaped paths.
strings=set(re.findall(r'["\']([^"\']{2,240})["\']',t))
paths=sorted(x for x in strings if x.startswith('/') and any(k in x.lower() for k in ['api','player','team','club','match','round','gameweek','stat','rank','leader','season','fantasy','squad','fixture','transfer']))
keywords=['baseUrl','baseURL','apiUrl','apiURL','Dio','Authorization','Bearer','players','statistics','leaderboard','fantasy','season','matchday','Funatix','firebase']
contexts=[]
for needle in keywords:
 for m in list(re.finditer(re.escape(needle),t,re.I))[:40]:
  ctx=t[max(0,m.start()-1200):min(len(t),m.start()+2400)]
  contexts.append({'needle':needle,'offset':m.start(),'text':ctx,'urls':re.findall(r'https?://[^"\'\\\s<>]+',ctx),'paths':sorted(set(x for x in re.findall(r'["\'](/[^"\']{1,220})["\']',ctx) if len(x)<220))[:150]})
# Domain inventory helps isolate actual API hosts from analytics/CDNs.
domains=[]
for u in urls:
 m=re.match(r'https?://([^/]+)',u)
 if m:domains.append(m.group(1).lower())
from collections import Counter
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V2','bundle':{'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':sha(b)},'url_count':len(urls),'interesting_urls':interesting_urls,'domain_counts':dict(Counter(domains).most_common()),'route_like_paths':paths,'contexts':contexts,'governance':{'authenticated_surface_accessed':False,'api_requests_made':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'bundle_bytes':len(b),'url_count':len(urls),'interesting_urls':interesting_urls[:100],'route_like_paths':paths[:150],'domain_counts':dict(Counter(domains).most_common(30))},ensure_ascii=False,indent=2))
