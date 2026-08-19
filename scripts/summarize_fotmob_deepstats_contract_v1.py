#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

SRC = Path('.nexus-fotmob-deepstats-contract-v1-status/RESULT.json')
OUT = Path('/mnt/data/nexus-fotmob-deepstats-contract-v1-summary')
OUT.mkdir(parents=True, exist_ok=True)

obj = json.loads(SRC.read_text(encoding='utf-8'))
contexts = []
for hit in obj.get('hits', []):
    needles = sorted(set(c.get('needle') for c in hit.get('contexts', []) if c.get('needle')))
    apiish = sorted(set(
        v
        for c in hit.get('contexts', [])
        for v in c.get('apiish', [])
        if isinstance(v, str) and '/api/' in v.lower()
    ))
    if apiish or any(n in needles for n in ['hasDeepStats', 'entryId', 'statSeasons', 'seasonEntries', 'deepStats', 'playerStats', 'seasonStats']):
        contexts.append({
            'url': hit.get('url'),
            'needles': needles,
            'api_candidates': apiish[:100],
        })

summary = {
    'schema': 'NEXUS_FOTMOB_DEEPSTATS_CONTRACT_SUMMARY_V1',
    'source_schema': obj.get('schema'),
    'source_status': obj.get('status'),
    'page': obj.get('page'),
    'declared_script_count': obj.get('declared_script_count'),
    'hit_files': obj.get('hit_files'),
    'api_candidates': obj.get('api_candidates', []),
    'relevant_contexts': contexts,
    'errors_count': len(obj.get('errors', [])),
    'governance': obj.get('governance'),
}
(OUT / 'SUMMARY.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=2))
