#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
SRC=Path('.nexus-slgr-fantasy-public-probe-v9-status/RESULT.json')
OUT=Path('.nexus-slgr-fantasy-public-probe-v9-status/TINY.json')
o=json.loads(SRC.read_text(encoding='utf-8'))
priority=['players_list','playersList','players-list','players-lists','schedule_id','scheduleId','league_id','leagueId','fantasy_league','matchday_id','matchdayId']
rows=[]
for needle in priority:
 hs=[h for h in o.get('hits',[]) if h.get('needle')==needle]
 for h in hs[:3]:
  rows.append({'needle':needle,'offset':h.get('offset'),'apiish_strings':(h.get('apiish_strings') or [])[:30],'integer_literals':(h.get('integer_literals') or [])[:60],'context':(h.get('context') or '')[:1200]})
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V9_TINY','hit_counts':o.get('hit_counts'),'rows':rows,'governance':o.get('governance')}
OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))
