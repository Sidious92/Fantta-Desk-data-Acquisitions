#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
SRC=Path('.nexus-slgr-fantasy-public-probe-v4-status/RESULT.json')
OUT=Path('.nexus-slgr-fantasy-public-probe-v4-status/ENDPOINTS.json')
o=json.loads(SRC.read_text(encoding='utf-8'))
rows=[]
for c in o.get('request_contracts',[]):
 rows.append({'class':c.get('class'),'gaJ_body':c.get('gaJ_body'),'gbD_body':c.get('gbD_body'),'string_literals':c.get('string_literals') or [],'query_keys':c.get('query_keys') or []})
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V4_ENDPOINT_INVENTORY','api_base':o.get('api_base'),'league_config_evidence':o.get('league_config_evidence'),'endpoint_count':len(rows),'endpoints':rows,'governance':o.get('governance')}
OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))
