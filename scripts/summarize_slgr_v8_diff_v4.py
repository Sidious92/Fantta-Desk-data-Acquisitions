#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
V8=Path('.nexus-slgr-fantasy-public-probe-v8-status/RESULT.json')
V4=Path('.nexus-slgr-fantasy-public-probe-v4-status/RESULT.json')
OUT=Path('.nexus-slgr-fantasy-public-probe-v8-status/DIFF_V4.json')
a=json.loads(V8.read_text(encoding='utf-8'));b=json.loads(V4.read_text(encoding='utf-8'))
def key(x):return (x.get('gaJ_body'),x.get('gbD_body'))
old={key(x) for x in b.get('request_contracts',[])}
new=[x for x in a.get('request_contracts',[]) if key(x) not in old]
rows=[{k:x.get(k) for k in ['class','gaJ_body','gbD_body','string_literals','query_keys']} for x in new]
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V8_DIFF_V4','v8_count':len(a.get('request_contracts',[])),'v4_count':len(b.get('request_contracts',[])),'new_contract_count':len(rows),'new_contracts':rows,'governance':{'api_requests_made':False,'predictive_models_modified':False,'decision_layer_started':False}}
OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(res,ensure_ascii=False,indent=2))
