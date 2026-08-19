#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin

import requests

PAGE = 'https://ligue1.com/en/fantasy'
API = 'https://api.mpg.football/fantasy'
OUT = Path('/mnt/data/nexus-ligue1-historical-contract-v1')
OUT.mkdir(parents=True, exist_ok=True)
HEADERS_PAGE = {
    'User-Agent': 'Mozilla/5.0 FantaNexus research acquisition',
    'Accept': 'text/html,application/javascript,*/*',
}
HEADERS_API = {
    'User-Agent': 'Mozilla/5.0 FantaNexus research acquisition',
    'Accept': 'application/json,text/plain,*/*',
    'Referer': PAGE,
    'platform': 'web',
    'application': 'ligue1',
}
TERMS = [
    'seasonsHistory', 'firstSeason', 'seasonId', 'season_id', 'season=',
    'historical', 'history', 'previousSeason', 'previous-season',
    'championship-player-stats', 'championship-players-pool',
    'championships-settings', 'gameWeek', 'gameweek'
]
BLOCKED = ['/auth', '/coach', '/user', '/profile', '/my-team', '/entry', '/league/']


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get_page(url: str):
    return requests.get(url, headers=HEADERS_PAGE, timeout=(8, 30), allow_redirects=True)


def get_api(route: str):
    return requests.get(API + route, headers=HEADERS_API, timeout=(8, 30), allow_redirects=True)


def json_meta(r: requests.Response):
    b = r.content
    out = {
        'url': r.url,
        'status': r.status_code,
        'content_type': r.headers.get('content-type', ''),
        'bytes': len(b),
        'sha256': sha(b),
    }
    try:
        o = r.json()
        out['json_type'] = type(o).__name__
        out['json_keys'] = list(o)[:100] if isinstance(o, dict) else None
        out['json'] = o
    except Exception as e:
        out['json_error'] = repr(e)
        out['preview'] = r.text[:1000]
    return out


def season_nodes(obj):
    rows = []
    def walk(x, path='$'):
        if isinstance(x, dict):
            for k, v in x.items():
                kl = str(k).lower()
                if any(t in kl for t in ['season', 'year', 'gameweek', 'round']):
                    rows.append({'path': f'{path}.{k}', 'key': k, 'value': v if not isinstance(v, (dict, list)) else None, 'container_type': type(v).__name__})
                if isinstance(v, (dict, list)):
                    walk(v, f'{path}.{k}')
        elif isinstance(x, list):
            for i, v in enumerate(x):
                if isinstance(v, (dict, list)):
                    walk(v, f'{path}[{i}]')
    walk(obj)
    return rows[:2000]


page = get_page(PAGE)
page.raise_for_status()
html = page.text
srcs = list(dict.fromkeys(urljoin(page.url, s) for s in re.findall(r'<script[^>]+src=["\']([^"\']+)', html, re.I)))

# Baseline settings are already a proven public route; inspect season semantics exactly.
settings_r = get_api('/championships-settings')
settings = json_meta(settings_r)
settings_nodes = season_nodes(settings.get('json')) if 'json' in settings else []


def scan_asset(url: str):
    try:
        r = get_page(url)
        ctype = r.headers.get('content-type', '').lower()
        if r.status_code != 200 or 'html' in ctype:
            return None
        text = r.text
        contexts = []
        route_candidates = set()
        for term in TERMS:
            for m in list(re.finditer(re.escape(term), text, re.I))[:100]:
                ctx = text[max(0, m.start() - 1800): min(len(text), m.start() + 3500)]
                # Extract literal slash-routes and URL fragments from local context only.
                for val in re.findall(r'["\'`](/[^"\'`\\]{1,300})["\'`]', ctx):
                    low = val.lower()
                    if any(x in low for x in ['season', 'history', 'championship', 'gameweek', 'round']):
                        route_candidates.add(val)
                contexts.append({'term': term, 'offset': m.start(), 'context': ctx})
        if not contexts:
            return None
        return {
            'url': r.url,
            'bytes': len(r.content),
            'sha256': sha(r.content),
            'route_candidates': sorted(route_candidates),
            'contexts': contexts[:250],
        }
    except Exception as e:
        return {'url': url, 'error': repr(e), 'route_candidates': [], 'contexts': []}


hits = []
with ThreadPoolExecutor(max_workers=8) as ex:
    futs = [ex.submit(scan_asset, u) for u in srcs]
    for fut in as_completed(futs):
        item = fut.result()
        if item:
            hits.append(item)

routes = sorted(set(r for h in hits for r in h.get('route_candidates', [])))
# Exact literal-only public probes. No templates, no auth/user contexts, no ID guessing.
testable = []
for route in routes:
    low = route.lower()
    if '${' in route or '{' in route or '}' in route:
        continue
    if any(x in low for x in BLOCKED):
        continue
    if not route.startswith('/'):
        continue
    if any(t in low for t in ['season', 'history', 'gameweek', 'round']):
        testable.append(route)

tests = []
for route in testable[:50]:
    try:
        r = get_api(route)
        meta = json_meta(r)
        meta.pop('json', None)
        meta['route'] = route
        tests.append(meta)
    except Exception as e:
        tests.append({'route': route, 'error': repr(e)})

result = {
    'schema': 'NEXUS_LIGUE1_HISTORICAL_FANTASY_CONTRACT_PROBE_V1',
    'page': {'url': page.url, 'status': page.status_code, 'bytes': len(page.content), 'sha256': sha(page.content)},
    'settings': {k: v for k, v in settings.items() if k != 'json'},
    'settings_season_nodes': settings_nodes,
    'script_count': len(srcs),
    'hit_files': len([h for h in hits if not h.get('error')]),
    'route_candidates': routes,
    'exact_historical_like_routes_tested': tests,
    'hits': hits,
    'governance': {
        'public_unauthenticated_surfaces_only': True,
        'only_frontend_declared_assets_scanned': True,
        'only_exact_literal_routes_called': True,
        'template_parameters_guessed': False,
        'season_ids_guessed': False,
        'authenticated_surface_accessed': False,
        'private_user_or_coach_routes_accessed': False,
        'predictive_models_modified': False,
        'decision_layer_started': False,
    },
}
# Discovery PASS means evidence was captured; it does NOT assert historical data availability.
result['status'] = 'PASS_DISCOVERY' if settings_r.status_code == 200 and hits else 'FAIL_CLOSED_DISCOVERY'
(OUT / 'RESULT.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({
    'status': result['status'],
    'settings_season_nodes': settings_nodes[:80],
    'route_candidates': routes,
    'tests': tests,
    'hit_files': result['hit_files'],
}, ensure_ascii=False, indent=2))
