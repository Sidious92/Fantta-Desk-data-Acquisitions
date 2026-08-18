#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
SRC=Path('.nexus-fotmob-nextdata-career-v3-status/RESULT.json')
OUT=Path('.nexus-fotmob-nextdata-career-v3-status/SUMMARY.json')
o=json.loads(SRC.read_text(encoding='utf-8'))
TARGETS=['statSeasons','firstSeasonStats','careerHistory','seasons','seasonName','tournaments','tournamentId','goals','matches','appearances']
def compact(v,depth=0):
 if depth>3:return {'type':type(v).__name__}
 if isinstance(v,dict):
  d={}
  for k,z in v.items():
   if k in TARGETS or depth<1:
    d[k]=compact(z,depth+1)
  return {'type':'dict','keys':list(v.keys())[:120],'data':d}
 if isinstance(v,list):
  return {'type':'list','len':len(v),'sample':[compact(x,depth+1) for x in v[:8]]}
 return v
rows=[]
for p in o.get('players',[]):
 hs=[]
 for h in p.get('next_data_hits') or []:
  ik=set(h.get('interesting_keys') or [])
  if ik.intersection({'statSeasons','firstSeasonStats','careerHistory','seasons'}):
   obj=h.get('object') or {}
   vals={k:compact(obj.get(k)) for k in TARGETS if k in obj}
   hs.append({'path':h.get('path'),'interesting_keys':sorted(ik),'object_keys':list(obj.keys())[:160],'target_values':vals})
 rows.append({'name':p.get('name'),'id':p.get('id'),'status':p.get('status'),'next_data_present':p.get('next_data_present'),'next_hit_count':len(p.get('next_data_hits') or []),'career_hits':hs[:40],'flight_payload_count':p.get('flight_payload_count')})
res={'schema':'NEXUS_FOTMOB_PUBLIC_NEXTDATA_CAREER_PROBE_V3_SUMMARY','players':rows,'governance':o.get('governance')}
OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2,default=str))
