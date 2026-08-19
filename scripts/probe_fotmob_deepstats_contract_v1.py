#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import requests

PAGE = 'https://www.fotmob.com/players/1190371/matija-frigan'
OUT = Path('/mnt/data/nexus-fotmob-deepstats-contract-v1')
OUT.mkdir(parents=True, exist_ok=True)
HEADERS = {
    'User-Agent': 'Mozilla/5.0 FantaNexus research acquisition',
    'Accept': 'text/html,application/javascript,*/*',
}
NEEDLES = [
    'hasDeepStats', 'entryId', 'statSeasons', 'seasonEntries', 'careerHistory',
    'deepStats', 'playerStats', 'seasonStats', 'statistics', 'tournamentId',
    '/api/data/player', '/api/data/players', 'stats?','career'
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, timeout: int = 25):
    return requests.get(url, headers=HEADERS, timeout=(8, timeout), allow_redirects=True)


def apiish_from_context(ctx: str):
    literals = re.findall(r'["\']([^"\']{1,400})["\']', ctx)
    templates = re.findall(r'`([^`]{1,400})`', ctx)
    values = []
    for value in literals + templates:
        low = value.lower()
        if any(k in low for k in ['/api/', 'stat', 'career', 'player', 'season', 'tournament', 'entry']):
            values.append(value)
    return sorted(set(values))[:250]


page = fetch(PAGE)
page.raise_for_status()
html = page.text
srcs = list(dict.fromkeys(urljoin(page.url, x) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)', html, re.I)))


def scan(url: str):
    try:
        r = fetch(url, 20)
        text = r.text
        ctype = r.headers.get('content-type', '').lower()
        if 'html' in ctype:
            return None
        contexts = []
        for needle in NEEDLES:
            for m in list(re.finditer(re.escape(needle), text, re.I))[:80]:
                ctx = text[max(0, m.start() - 2400): min(len(text), m.start() + 5200)]
                contexts.append({
                    'needle': needle,
                    'offset': m.start(),
                    'apiish': apiish_from_context(ctx),
                    'context': ctx,
                })
        if not contexts:
            return None
        return {
            'url': r.url,
            'status': r.status_code,
            'bytes': len(r.content),
            'sha256': sha256(r.content),
            'contexts': contexts,
        }
    except Exception as e:
        return {'url': url, 'error': repr(e), 'contexts': []}


hits, errors = [], []
with ThreadPoolExecutor(max_workers=8) as ex:
    futures = [ex.submit(scan, url) for url in srcs]
    for fut in as_completed(futures):
        item = fut.result()
        if not item:
            continue
        if item.get('error'):
            errors.append({'url': item['url'], 'error': item['error']})
        else:
            hits.append(item)

# Extract unique API-looking strings as a compact contract candidate index.
api_candidates = []
for hit in hits:
    for ctx in hit['contexts']:
        for value in ctx['apiish']:
            if '/api/' in value.lower():
                api_candidates.append(value)
api_candidates = sorted(set(api_candidates))

result = {
    'schema': 'NEXUS_FOTMOB_DEEPSTATS_CONTRACT_PROBE_V1',
    'page': {
        'url': page.url,
        'status': page.status_code,
        'bytes': len(page.content),
        'sha256': sha256(page.content),
    },
    'needles': NEEDLES,
    'declared_script_count': len(srcs),
    'hit_files': len(hits),
    'api_candidates': api_candidates,
    'hits': hits,
    'errors': errors,
    'governance': {
        'only_public_page_declared_assets_requested': True,
        'discovered_api_endpoints_called': False,
        'authenticated_surface_accessed': False,
        'private_routes_accessed': False,
        'bruteforce_ids': False,
        'predictive_models_modified': False,
        'decision_layer_started': False,
    },
}
result['status'] = 'PASS_DISCOVERY' if hits else 'FAIL_CLOSED_NO_CONTRACT_HINTS'

(OUT / 'RESULT.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({
    'status': result['status'],
    'scripts': len(srcs),
    'hit_files': len(hits),
    'api_candidates': api_candidates[:100],
    'contexts': [
        {
            'url': h['url'],
            'needles': sorted(set(c['needle'] for c in h['contexts'])),
            'apiish': sorted(set(v for c in h['contexts'] for v in c['apiish']))[:80],
        }
        for h in hits[:20]
    ],
}, ensure_ascii=False, indent=2))
