#!/usr/bin/env python3
from __future__ import annotations
import json,re
from pathlib import Path
SRC=Path('.nexus-fotmob-player-page-probe-v2-status/RESULT.json')
OUT=Path('.nexus-fotmob-player-page-probe-v2-status/SUMMARY.json')
o=json.loads(SRC.read_text(encoding='utf-8'))
NEEDLES=['statSeasons','careerHistory','career','season','league','playerData','player-data','goals','matches','tournament','__NEXT_DATA__','self.__next_f.push']
players=[]
for p in o.get('players',[]):
 contexts=p.get('contexts') or {}
 compact={}
 for n in NEEDLES:
  vals=contexts.get(n) or []
  if vals:
   compact[n]=[]
   for v in vals[:12]:
    # Preserve exact local context but cap size; inventory likely JSON keys and API-ish strings.
    keys=sorted(set(re.findall(r'["\']([A-Za-z][A-Za-z0-9_]{2,80})["\']\s*:',v)))
    urls=sorted(set(re.findall(r'https?://[^"\'\\\s<>]+',v)))
    compact[n].append({'text':v[:3500],'json_like_keys':keys[:180],'urls':urls[:80]})
 scripts=[]
 for s in p.get('scripts') or []:
  if s.get('src'):
   scripts.append({'src':s.get('src'),'type':s.get('type')})
  elif s.get('inline'):
   body=s['inline']
   if any(n.lower() in body.lower() for n in NEEDLES):
    scripts.append({'type':s.get('type'),'inline_preview':body[:7000],'json_like_keys':sorted(set(re.findall(r'["\']([A-Za-z][A-Za-z0-9_]{2,80})["\']\s*:',body)))[:220]})
 players.append({'name':p.get('name'),'id':p.get('id'),'url':p.get('url'),'status':p.get('status'),'bytes':p.get('bytes'),'contexts':compact,'declared_script_srcs':scripts[:120],'embedded_urls':(p.get('embedded_urls') or [])[:160]})
res={'schema':'NEXUS_FOTMOB_PUBLIC_PLAYER_PAGE_PAYLOAD_PROBE_V2_SUMMARY','players':players,'governance':o.get('governance')}
OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'players':[{'name':p['name'],'context_keys':list(p['contexts']),'script_srcs':len(p['declared_script_srcs']),'embedded_urls':len(p['embedded_urls'])} for p in players]},ensure_ascii=False,indent=2))
