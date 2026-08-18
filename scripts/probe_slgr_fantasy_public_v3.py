#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
import requests
URL='https://fantasy.slgr.gr/main.dart.js'
OUT=Path('/mnt/data/nexus-slgr-fantasy-public-probe-v3');OUT.mkdir(parents=True,exist_ok=True)
NEEDLES=['https://fantaking-api.dunkest.com/api/v1','/players','/players/','/players-lists/','/matchdays','/matchdays/','/fantasy-leaders','/fantasy-pts','/stats/players/table/download','/:leagueId/stats','/:leagueId/player-reports']
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/javascript,*/*','Referer':'https://fantasy.slgr.gr/'})
r=s.get(URL,timeout=90);r.raise_for_status();t=r.text;b=r.content
hits=[]
for needle in NEEDLES:
 for m in list(re.finditer(re.escape(needle),t))[:40]:
  ctx=t[max(0,m.start()-3500):min(len(t),m.start()+6000)]
  strings=sorted(set(re.findall(r'["\']([^"\']{1,260})["\']',ctx)))
  templates=sorted(set(re.findall(r'`([^`]{1,260})`',ctx)))
  apiish=[x for x in strings if x.startswith('/') or 'api' in x.lower() or any(k in x.lower() for k in ['league','season','player','matchday','fantasy','stats'])]
  hits.append({'needle':needle,'offset':m.start(),'apiish_strings':apiish[:400],'templates':templates[:250],'context':ctx})
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V3','bundle':{'url':r.url,'status':r.status_code,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()},'needles':NEEDLES,'hits':hits,'hit_counts':{n:sum(1 for h in hits if h['needle']==n) for n in NEEDLES},'governance':{'api_requests_made':False,'authenticated_surface_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'hit_counts':res['hit_counts'],'sample_apiish':{n:next((h['apiish_strings'] for h in hits if h['needle']==n),[]) for n in NEEDLES}},ensure_ascii=False,indent=2))
