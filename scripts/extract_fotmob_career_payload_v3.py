#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
SRC=Path('.nexus-fotmob-nextdata-career-v3-status/RESULT.json')
OUT=Path('.nexus-fotmob-nextdata-career-v3-status/CAREER_EXTRACT.json')
o=json.loads(SRC.read_text(encoding='utf-8'))
rows=[]
for p in o.get('players',[]):
 data_hit=next((h for h in p.get('next_data_hits',[]) if h.get('path')=='$.props.pageProps.data'),None)
 if not data_hit:
  data_hit=next((h for h in p.get('next_data_hits',[]) if {'statSeasons','careerHistory'}.intersection(set(h.get('interesting_keys') or []))),None)
 obj=(data_hit or {}).get('object') or {}
 seasons=[]
 for s in obj.get('statSeasons') or []:
  if not isinstance(s,dict):continue
  seasons.append({'seasonName':s.get('seasonName'),'tournaments':[{'name':t.get('name'),'tournamentId':t.get('tournamentId'),'entryId':t.get('entryId'),'hasDeepStats':t.get('hasDeepStats')} for t in (s.get('tournaments') or []) if isinstance(t,dict)]})
 fs=obj.get('firstSeasonStats') or {}
 tsc=fs.get('topStatCard') if isinstance(fs,dict) else None
 rows.append({'name':p.get('name'),'id':p.get('id'),'statSeasons':seasons,'careerHistory':obj.get('careerHistory'),'firstSeasonTopStatCard':tsc,'primaryTeam':obj.get('primaryTeam'),'mainLeague':obj.get('mainLeague'),'dataProvider':obj.get('dataProvider'),'ssr':obj.get('ssr')})
res={'schema':'NEXUS_FOTMOB_PUBLIC_CAREER_PAYLOAD_EXTRACT_V3','players':rows,'governance':o.get('governance')}
OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2,default=str))
