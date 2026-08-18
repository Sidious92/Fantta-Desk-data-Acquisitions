#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
SRC=Path('.nexus-slgr-fantasy-public-probe-v2-status/RESULT.json')
OUT=Path('.nexus-slgr-fantasy-public-probe-v2-status/SUMMARY.json')
o=json.loads(SRC.read_text(encoding='utf-8'))
interesting=o.get('interesting_urls') or []
paths=o.get('route_like_paths') or []
contexts=o.get('contexts') or []
# Keep only contexts that reveal non-analytics host/endpoint/config/auth semantics.
selected=[]
for c in contexts:
 text=(c.get('text') or '')
 if any(k in text.lower() for k in ['fantasy.slgr','funatix','api.', '/api/', 'baseurl','apiurl','authorization','bearer','player','leaderboard','statistics','season']):
  selected.append({'needle':c.get('needle'),'offset':c.get('offset'),'urls':c.get('urls') or [],'paths':c.get('paths') or [],'text':text[:5000]})
summary={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V2_SUMMARY','bundle':o.get('bundle'),'interesting_urls':interesting,'domain_counts':o.get('domain_counts'),'route_like_paths':paths,'selected_contexts':selected[:160],'selected_context_count':len(selected),'governance':o.get('governance')}
OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'bundle':summary['bundle'],'interesting_urls':interesting,'route_like_paths':paths,'selected_context_count':len(selected)},ensure_ascii=False,indent=2))
