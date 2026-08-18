#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
SRC=Path('.nexus-slgr-fantasy-public-probe-v4-status/RESULT.json')
OUT=Path('.nexus-slgr-fantasy-public-probe-v4-status/SUMMARY.json')
o=json.loads(SRC.read_text(encoding='utf-8'))
TOKENS=['/leagues','/competitions','/players-lists','/players/','/matchdays','/schedules','/stats/players','/fantasy-leaders','/fantasy-pts','/teams','/fixtures']
selected=[]
for c in o.get('request_contracts',[]):
 body=(c.get('gaJ_body') or '')+' '+(c.get('gbD_body') or '')
 if any(tok in body for tok in TOKENS):
  selected.append({k:c.get(k) for k in ['class','gaJ_body','gbD_body','string_literals','query_keys']})
summary={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V4_SUMMARY','api_base':o.get('api_base'),'league_config_evidence':o.get('league_config_evidence'),'selected_contract_count':len(selected),'selected_contracts':selected,'governance':o.get('governance')}
OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
