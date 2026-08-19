#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

SRC = Path('.nexus-fotmob-deepstats-contract-v1-status/RESULT.json')
OUT = Path('/mnt/data/nexus-fotmob-playerstats-contract-v2')
OUT.mkdir(parents=True, exist_ok=True)

obj = json.loads(SRC.read_text(encoding='utf-8'))
needles = ['/api/data/playerStats', 'playerStats', 'entryId', 'seasonStats', 'statSeasons', 'tournamentId']
extracts = []
seen = set()

for hit in obj.get('hits', []):
    url = hit.get('url')
    for ctx in hit.get('contexts', []):
        text = ctx.get('context') or ''
        if '/api/data/playerStats' not in text:
            continue
        # One compact snippet per distinct occurrence in the stored context.
        start = 0
        while True:
            pos = text.find('/api/data/playerStats', start)
            if pos < 0:
                break
            snippet = text[max(0, pos - 3500): min(len(text), pos + 5000)]
            key = (url, snippet)
            if key not in seen:
                seen.add(key)
                extracts.append({
                    'url': url,
                    'source_needle': ctx.get('needle'),
                    'signals': [n for n in needles if n in snippet],
                    'snippet': snippet,
                })
            start = pos + 1

result = {
    'schema': 'NEXUS_FOTMOB_PLAYERSTATS_CONTRACT_EXTRACT_V2',
    'source_status': obj.get('status'),
    'endpoint': '/api/data/playerStats',
    'extract_count': len(extracts),
    'extracts': extracts[:12],
    'governance': {
        'source_is_persisted_public_asset_probe': True,
        'endpoint_called': False,
        'predictive_models_modified': False,
        'decision_layer_started': False,
    },
}
result['status'] = 'PASS_EXTRACT' if extracts else 'FAIL_CLOSED_NO_ENDPOINT_CONTEXT'
(OUT / 'CONTRACT.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({k: result[k] for k in ['schema','status','endpoint','extract_count']}, ensure_ascii=False, indent=2))
