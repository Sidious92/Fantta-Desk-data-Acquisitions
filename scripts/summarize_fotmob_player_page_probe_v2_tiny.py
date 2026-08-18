#!/usr/bin/env python3
from __future__ import annotations
import json,re
from pathlib import Path
SRC=Path('.nexus-fotmob-player-page-probe-v2-status/SUMMARY.json')
OUT=Path('.nexus-fotmob-player-page-probe-v2-status/TINY.json')
o=json.loads(SRC.read_text(encoding='utf-8'))
rows=[]
for p in o.get('players',[]):
 contexts=p.get('contexts') or {}
 srcs=[s.get('src') for s in p.get('declared_script_srcs',[]) if s.get('src')]
 # Collect a tiny inventory of JSON-like keys around the strongest career/season contexts.
 strong={}
 for n in ['statSeasons','careerHistory','career','season','goals','matches','tournament','__NEXT_DATA__','self.__next_f.push']:
  vals=contexts.get(n) or []
  keys=[];texts=[];urls=[]
  for v in vals[:5]:
   keys.extend(v.get('json_like_keys') or []);urls.extend(v.get('urls') or []);texts.append((v.get('text') or '')[:700])
  if vals:strong[n]={'hits':len(vals),'keys':sorted(set(keys))[:80],'urls':sorted(set(urls))[:30],'text_samples':texts[:2]}
 rows.append({'name':p.get('name'),'id':p.get('id'),'status':p.get('status'),'bytes':p.get('bytes'),'context_sections':list(contexts.keys()),'strong_contexts':strong,'script_src_count':len(srcs),'script_srcs':srcs[:40],'embedded_urls':(p.get('embedded_urls') or [])[:50]})
res={'schema':'NEXUS_FOTMOB_PUBLIC_PLAYER_PAGE_PAYLOAD_PROBE_V2_TINY','players':rows,'governance':o.get('governance')}
OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))
