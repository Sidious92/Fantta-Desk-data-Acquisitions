#!/usr/bin/env python3
from __future__ import annotations
import json
from collections import Counter
from pathlib import Path
SRC=Path('.nexus-ligue1-official-fantasy-api-probe-v8-status/RESULT.json')
OUT=Path('.nexus-ligue1-official-fantasy-api-probe-v8-status/SUMMARY.json')
obj=json.loads(SRC.read_text(encoding='utf-8'))
calls=obj.get('api_call_sites') or []
def compact(c):
 return {
  'method':c.get('method'),
  'route_candidates':c.get('route_candidates') or [],
  'pages':c.get('pages') or [],
  'classification':c.get('classification'),
  'auth_context_markers':c.get('auth_context_markers') or [],
  'url':c.get('url'),
  'depth':c.get('depth'),
  'argument_excerpt':c.get('argument_excerpt')
 }
summary={
 'schema':'NEXUS_LIGUE1_OFFICIAL_FANTASY_API_PUBLIC_PROBE_V8_SUMMARY',
 'source_schema':obj.get('schema'),
 'crawl':obj.get('crawl'),
 'call_site_count':len(calls),
 'classification_counts':dict(Counter(c.get('classification') for c in calls)),
 'method_counts':dict(Counter(c.get('method') for c in calls)),
 'public_context_candidates':[compact(c) for c in calls if c.get('classification')=='PUBLIC_CONTEXT_CANDIDATE'],
 'auth_context_calls':[compact(c) for c in calls if c.get('classification')=='AUTH_CONTEXT'],
 'route_inventory':sorted({r for c in calls for r in (c.get('route_candidates') or [])}),
 'errors_count':len(obj.get('errors') or []),
 'governance':obj.get('governance')
}
OUT.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
