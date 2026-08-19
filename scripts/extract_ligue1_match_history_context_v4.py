#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

SRC=Path('.nexus-ligue1-historical-contract-v1-status/RESULT.json')
OUT=Path('/mnt/data/nexus-ligue1-match-history-context-v4')
OUT.mkdir(parents=True,exist_ok=True)
obj=json.loads(SRC.read_text(encoding='utf-8'))
rows=[]
for hit in obj.get('hits',[]):
    url=hit.get('url')
    for ctx in hit.get('contexts',[]):
        text=ctx.get('context') or ''
        if 'match-history' in text or '/match-sheet/' in text:
            pos=text.find('match-history')
            if pos<0:pos=text.find('/match-sheet/')
            snip=text[max(0,pos-4500):min(len(text),pos+5500)] if pos>=0 else text[:10000]
            rows.append({'asset_url':url,'term':ctx.get('term'),'snippet':snip})
result={
 'schema':'NEXUS_LIGUE1_MATCH_HISTORY_CONTEXT_V4',
 'status':'PASS_CONTEXT' if rows else 'FAIL_CLOSED_NO_CONTEXT',
 'rows':rows[:20],
 'governance':{
  'source':'persisted-public-frontend-probe-v1',
  'endpoint_called':False,
  'parameter_transformation_guessed':False,
  'predictive_models_modified':False,
  'decision_layer_started':False
 }
}
(OUT/'CONTEXT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':result['status'],'rows':len(rows)},ensure_ascii=False,indent=2))
