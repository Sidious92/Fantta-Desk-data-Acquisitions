#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

SRC = Path('.nexus-fotmob-playerstats-smoke-v3-status/RESULT.json')
OUT = Path('/mnt/data/nexus-fotmob-playerstats-smoke-v3-summary')
OUT.mkdir(parents=True, exist_ok=True)

obj = json.loads(SRC.read_text(encoding='utf-8'))
rows = []
for t in obj.get('tests', []):
    ids = []
    for s in t.get('stat_index', []):
        sid = s.get('localizedTitleId')
        if sid and sid not in ids:
            ids.append(sid)
    rows.append({
        'name': t.get('name'),
        'playerId': t.get('playerId'),
        'status': t.get('status'),
        'chosen': t.get('chosen'),
        'http_status': t.get('http_status'),
        'json_keys': t.get('json_keys'),
        'stat_ids': ids,
        'shot_count': len((t.get('json') or {}).get('shotmap') or []) if isinstance(t.get('json'), dict) else None,
    })
summary = {
    'schema': 'NEXUS_FOTMOB_PLAYERSTATS_SMOKE_V3_SUMMARY',
    'source_status': obj.get('status'),
    'pass_count': obj.get('pass_count'),
    'test_count': obj.get('test_count'),
    'players': rows,
    'governance': obj.get('governance'),
}
(OUT / 'SUMMARY.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=2))
