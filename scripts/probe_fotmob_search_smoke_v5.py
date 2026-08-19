#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

OUT = Path('/mnt/data/nexus-fotmob-search-smoke-v5')
OUT.mkdir(parents=True, exist_ok=True)
PLAYERS = ['Matija Frigan', 'Andrea Adorante', 'Kornel Lisman', 'Albion Rrahmani']
BASE = 'https://www.fotmob.com/api/data/search/suggest'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 FantaNexus research acquisition',
    'Accept': 'application/json,text/plain,*/*',
    'Referer': 'https://www.fotmob.com/',
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compact_players(obj):
    """Extract player-like objects without assuming the response envelope."""
    found = []

    def walk(x, path='$'):
        if isinstance(x, dict):
            typ = str(x.get('type', '')).lower()
            if typ == 'player' or ('id' in x and 'name' in x and ('primaryTeam' in x or 'teamName' in x)):
                found.append({
                    'path': path,
                    'type': x.get('type'),
                    'id': x.get('id'),
                    'name': x.get('name'),
                    'primaryTeam': x.get('primaryTeam'),
                    'teamName': x.get('teamName'),
                    'teamId': x.get('teamId'),
                })
            for k, v in x.items():
                walk(v, f'{path}.{k}')
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, f'{path}[{i}]')

    walk(obj)
    # Stable de-duplication by id/name/team context.
    out, seen = [], set()
    for x in found:
        key = (str(x.get('id')), str(x.get('name')), json.dumps(x.get('primaryTeam'), sort_keys=True, ensure_ascii=False), str(x.get('teamName')))
        if key not in seen:
            seen.add(key)
            out.append(x)
    return out


results = {
    'schema': 'NEXUS_FOTMOB_PUBLIC_SEARCH_SMOKE_V5',
    'endpoint': BASE,
    'players': PLAYERS,
    'tests': [],
    'governance': {
        'public_unauthenticated_endpoint_only': True,
        'authenticated_surface_accessed': False,
        'private_routes_accessed': False,
        'bruteforce_ids': False,
        'predictive_models_modified': False,
        'decision_layer_started': False,
    },
}

for name in PLAYERS:
    params = {'hits': '50', 'lang': 'en', 'term': name}
    url = BASE + '?' + urlencode(params)
    item = {'player': name, 'requested': url}
    try:
        r = requests.get(url, headers=HEADERS, timeout=(8, 25), allow_redirects=True)
        raw = r.content
        item.update({
            'url': r.url,
            'status': r.status_code,
            'content_type': r.headers.get('content-type', ''),
            'bytes': len(raw),
            'sha256': sha256(raw),
            'preview': r.text[:2000],
        })
        try:
            obj = r.json()
            item['json_type'] = type(obj).__name__
            item['json_keys'] = list(obj)[:100] if isinstance(obj, dict) else None
            item['player_candidates'] = compact_players(obj)
            item['json'] = obj
        except Exception as e:
            item['json_error'] = repr(e)
    except Exception as e:
        item['error'] = repr(e)
    results['tests'].append(item)
    time.sleep(0.35)

statuses = [x.get('status') for x in results['tests']]
results['status'] = 'PASS' if statuses and all(x == 200 for x in statuses) else 'FAIL_CLOSED'

(OUT / 'RESULT.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({
    'status': results['status'],
    'tests': [
        {
            'player': x['player'],
            'http': x.get('status'),
            'json_type': x.get('json_type'),
            'candidates': [
                {'id': c.get('id'), 'name': c.get('name'), 'primaryTeam': c.get('primaryTeam'), 'teamName': c.get('teamName')}
                for c in x.get('player_candidates', [])[:10]
            ],
        }
        for x in results['tests']
    ],
}, ensure_ascii=False, indent=2))
