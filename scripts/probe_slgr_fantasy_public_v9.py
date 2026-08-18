#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
import requests
URL='https://fantasy.slgr.gr/main.dart.js'
OUT=Path('/mnt/data/nexus-slgr-fantasy-public-probe-v9');OUT.mkdir(parents=True,exist_ok=True)
NEEDLES=['players_list','playersList','players-list','players-lists','schedule_id','scheduleId','schedule','league_id','leagueId','fantasy_league','matchday_id','matchdayId']
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/javascript,*/*','Referer':'https://fantasy.slgr.gr/'})
r=s.get(URL,timeout=90);r.raise_for_status();t=r.text;b=r.content
hits=[]
for needle in NEEDLES:
 for m in list(re.finditer(re.escape(needle),t,re.I))[:120]:
  ctx=t[max(0,m.start()-3200):min(len(t),m.start()+5200)]
  strings=sorted(set(re.findall(r'\\?"([^"\\]{1,260})\\?"',ctx)))
  ints=sorted(set(int(x) for x in re.findall(r'(?<![A-Za-z0-9_])(\d{1,7})(?![A-Za-z0-9_])',ctx) if int(x)<10000000))
  apiish=[x for x in strings if x.startswith('/') or any(k in x.lower() for k in ['player','schedule','league','matchday','fantasy','season','competition'])]
  hits.append({'needle':needle,'offset':m.start(),'apiish_strings':apiish[:250],'integer_literals':ints[:300],'context':ctx})
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V9','bundle':{'url':r.url,'status':r.status_code,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()},'needles':NEEDLES,'hit_counts':{n:sum(1 for h in hits if h['needle']==n) for n in NEEDLES},'hits':hits,'governance':{'api_requests_made':False,'authenticated_surface_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'hit_counts':res['hit_counts'],'samples':{n:next(({'apiish':h['apiish_strings'],'ints':h['integer_literals']} for h in hits if h['needle']==n),None) for n in NEEDLES}},ensure_ascii=False,indent=2))
