#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
SRC=Path('.nexus-slgr-fantasy-public-probe-v9-status/RESULT.json')
OUT=Path('.nexus-slgr-fantasy-public-probe-v9-status/SUMMARY.json')
o=json.loads(SRC.read_text(encoding='utf-8'))
selected=[]
for h in o.get('hits',[]):
 if h.get('needle') in {'players_list','playersList','players-list','players-lists','schedule_id','scheduleId','league_id','leagueId','fantasy_league','matchday_id','matchdayId'}:
  selected.append({'needle':h.get('needle'),'offset':h.get('offset'),'apiish_strings':h.get('apiish_strings') or [],'integer_literals':h.get('integer_literals') or [],'context':(h.get('context') or '')[:6000]})
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V9_SUMMARY','bundle':o.get('bundle'),'hit_counts':o.get('hit_counts'),'selected':selected[:240],'governance':o.get('governance')}
OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'hit_counts':res['hit_counts'],'selected_count':len(selected),'compact':[{'needle':x['needle'],'offset':x['offset'],'apiish':x['apiish_strings'][:20],'ints':x['integer_literals'][:50]} for x in selected[:50]]},ensure_ascii=False,indent=2))
