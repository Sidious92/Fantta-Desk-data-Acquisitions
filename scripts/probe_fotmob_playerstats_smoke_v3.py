#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

SRC = Path('.nexus-fotmob-nextdata-career-v3-status/RESULT.json')
OUT = Path('/mnt/data/nexus-fotmob-playerstats-smoke-v3')
OUT.mkdir(parents=True, exist_ok=True)
ENDPOINT = 'https://www.fotmob.com/api/data/playerStats'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 FantaNexus research acquisition',
    'Accept': 'application/json,text/plain,*/*',
    'Referer': 'https://www.fotmob.com/',
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_stat_root(v, player_id):
    best = []
    def walk(x, path='$'):
        if isinstance(x, dict):
            if isinstance(x.get('statSeasons'), list):
                score = 0
                if str(x.get('id')) == str(player_id):
                    score += 10
                if 'firstSeasonStats' in x:
                    score += 5
                best.append((score, path, x))
            for k, z in x.items():
                if isinstance(z, (dict, list)):
                    walk(z, f'{path}.{k}')
        elif isinstance(x, list):
            for i, z in enumerate(x):
                if isinstance(z, (dict, list)):
                    walk(z, f'{path}[{i}]')
    walk(v)
    return max(best, key=lambda t: t[0]) if best else None


def season_options(root):
    rows = []
    for season in root.get('statSeasons') or []:
        season_name = season.get('seasonName')
        for t in season.get('tournaments') or []:
            rows.append({
                'seasonName': season_name,
                'entryId': t.get('entryId'),
                'tournamentId': t.get('tournamentId'),
                'tournamentName': t.get('name') or t.get('tournamentName'),
                'hasDeepStats': t.get('hasDeepStats'),
            })
    return rows


def stat_index(obj):
    out = []
    def walk(x, path='$'):
        if isinstance(x, dict):
            if 'localizedTitleId' in x and any(k in x for k in ['statValue', 'value', 'title', 'statTitle']):
                out.append({
                    'path': path,
                    'localizedTitleId': x.get('localizedTitleId'),
                    'title': x.get('title') or x.get('statTitle'),
                    'statValue': x.get('statValue'),
                    'value': x.get('value'),
                    'percentileRank': x.get('percentileRank'),
                })
            for k, z in x.items():
                if isinstance(z, (dict, list)):
                    walk(z, f'{path}.{k}')
        elif isinstance(x, list):
            for i, z in enumerate(x):
                if isinstance(z, (dict, list)):
                    walk(z, f'{path}[{i}]')
    walk(obj)
    seen, unique = set(), []
    for row in out:
        key = (row.get('localizedTitleId'), row.get('statValue'), row.get('value'))
        if key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


source = json.loads(SRC.read_text(encoding='utf-8'))
results = {
    'schema': 'NEXUS_FOTMOB_PLAYERSTATS_SMOKE_V3',
    'endpoint': ENDPOINT,
    'tests': [],
    'governance': {
        'season_ids_source': str(SRC),
        'only_observed_entry_ids_used': True,
        'public_unauthenticated_endpoint_only': True,
        'authenticated_surface_accessed': False,
        'private_routes_accessed': False,
        'bruteforce_ids': False,
        'predictive_models_modified': False,
        'decision_layer_started': False,
    },
}

for player in source.get('players', []):
    name = player.get('name')
    pid = player.get('id')
    rec = {'name': name, 'playerId': pid}
    root_hit = find_stat_root(player, pid)
    if not root_hit:
        rec['status'] = 'FAIL_CLOSED_NO_STATSEASONS'
        results['tests'].append(rec)
        continue
    _, root_path, root = root_hit
    options = season_options(root)
    rec['stat_root_path'] = root_path
    rec['available_seasons'] = options
    # UI treats the first option as embedded firstSeasonStats. Probe the first later
    # option that explicitly has deep stats; never invent an entryId.
    candidates = [x for i, x in enumerate(options) if i > 0 and x.get('entryId') is not None and x.get('hasDeepStats') is not False]
    if not candidates:
        candidates = [x for i, x in enumerate(options) if i > 0 and x.get('entryId') is not None]
    if not candidates:
        rec['status'] = 'FAIL_CLOSED_NO_HISTORICAL_ENTRYID'
        results['tests'].append(rec)
        continue
    chosen = candidates[0]
    rec['chosen'] = chosen
    params = {'playerId': str(pid), 'seasonId': str(chosen['entryId']), 'isFirstSeason': 'false'}
    try:
        r = requests.get(ENDPOINT, params=params, headers=HEADERS, timeout=(8, 30), allow_redirects=True)
        raw = r.content
        rec['request_url'] = r.url
        rec['http_status'] = r.status_code
        rec['content_type'] = r.headers.get('content-type', '')
        rec['bytes'] = len(raw)
        rec['sha256'] = sha256(raw)
        rec['preview'] = r.text[:2500]
        try:
            obj = r.json()
            rec['json_type'] = type(obj).__name__
            rec['json_keys'] = list(obj)[:100] if isinstance(obj, dict) else None
            rec['stat_index'] = stat_index(obj)
            rec['json'] = obj
            rec['status'] = 'PASS' if r.status_code == 200 and isinstance(obj, (dict, list)) else 'FAIL_CLOSED_HTTP_OR_JSON'
        except Exception as e:
            rec['json_error'] = repr(e)
            rec['status'] = 'FAIL_CLOSED_NON_JSON'
    except Exception as e:
        rec['error'] = repr(e)
        rec['status'] = 'FAIL_CLOSED_REQUEST_ERROR'
    results['tests'].append(rec)
    time.sleep(0.35)

passes = sum(1 for x in results['tests'] if x.get('status') == 'PASS')
results['pass_count'] = passes
results['test_count'] = len(results['tests'])
results['status'] = 'PASS' if passes == len(results['tests']) and passes > 0 else ('PARTIAL' if passes else 'FAIL_CLOSED')

(OUT / 'RESULT.json').write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps({
    'status': results['status'],
    'pass_count': passes,
    'tests': [
        {
            'name': x.get('name'),
            'status': x.get('status'),
            'chosen': x.get('chosen'),
            'http': x.get('http_status'),
            'json_keys': x.get('json_keys'),
            'stat_ids': [s.get('localizedTitleId') for s in x.get('stat_index', [])[:80]],
        }
        for x in results['tests']
    ],
}, ensure_ascii=False, indent=2))
