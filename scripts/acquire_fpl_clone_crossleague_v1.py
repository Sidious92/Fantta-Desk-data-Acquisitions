#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

OUT = Path('/mnt/data/nexus-fpl-clone-crossleague-v1')
OUT.mkdir(parents=True, exist_ok=True)

PROVIDERS = [
    {
        'key': 'liga_portugal',
        'provider': 'Fantasy Liga Portugal Betclic',
        'competition': 'Liga Portugal Betclic',
        'base': 'https://fantasy.ligaportugal.pt/api/',
        'source_protocol': 'NEXUS_LIGA_PORTUGAL_FANTASY_ACQUISITION_PROTOCOL_V1',
    },
    {
        'key': 'rsl',
        'provider': 'RSL Fantasy',
        'competition': 'Saudi Pro League',
        'base': 'https://fantasy.spl.com.sa/api/',
        'source_protocol': 'NEXUS_RSL_FANTASY_ACQUISITION_PROTOCOL_V1',
    },
    {
        'key': 'eliteserien',
        'provider': 'Fantasy Eliteserien',
        'competition': 'Eliteserien',
        'base': 'https://en.fantasy.eliteserien.no/api/',
        'source_protocol': 'NEXUS_SCANDINAVIAN_FPL_CLONES_ACQUISITION_PROTOCOL_V1',
    },
    {
        'key': 'allsvenskan',
        'provider': 'Allsvenskan Fantasy',
        'competition': 'Allsvenskan',
        'base': 'https://en.fantasy.allsvenskan.se/api/',
        'source_protocol': 'NEXUS_SCANDINAVIAN_FPL_CLONES_ACQUISITION_PROTOCOL_V1',
    },
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 FantaNexus research acquisition',
    'Accept': 'application/json,text/plain,*/*',
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def get(url: str, attempts: int = 4) -> requests.Response:
    last: Exception | None = None
    for i in range(attempts):
        try:
            r = requests.get(url, headers=HEADERS, timeout=(8, 35), allow_redirects=True)
            if r.status_code == 429 or 500 <= r.status_code < 600:
                time.sleep(min(8.0, 0.7 * (2 ** i)))
                continue
            return r
        except Exception as e:
            last = e
            time.sleep(min(8.0, 0.7 * (2 ** i)))
    if last:
        raise last
    raise RuntimeError(f'No response for {url}')


def fetch_json(url: str) -> tuple[Any | None, dict[str, Any]]:
    try:
        r = get(url)
        raw = r.content
        meta = {
            'url': r.url,
            'http_status': r.status_code,
            'content_type': r.headers.get('content-type', ''),
            'bytes': len(raw),
            'sha256': sha256(raw),
        }
        try:
            return r.json(), meta
        except Exception as e:
            meta['json_error'] = repr(e)
            meta['preview'] = r.text[:1000]
            return None, meta
    except Exception as e:
        return None, {'url': url, 'request_error': repr(e)}


def compact_element(e: dict[str, Any]) -> dict[str, Any]:
    keep = [
        'id','code','web_name','first_name','second_name','team','element_type',
        'status','now_cost','total_points','event_points','points_per_game',
        'minutes','goals_scored','assists','clean_sheets','goals_conceded',
        'own_goals','penalties_saved','penalties_missed','yellow_cards','red_cards',
        'saves','bonus','bps','influence','creativity','threat','ict_index',
        'starts','expected_goals','expected_assists','expected_goal_involvements',
        'expected_goals_conceded','selected_by_percent','form'
    ]
    return {k: e.get(k) for k in keep if k in e}


def acquire_provider(p: dict[str, str]) -> dict[str, Any]:
    key = p['key']
    pdir = OUT / key
    pdir.mkdir(parents=True, exist_ok=True)
    base = p['base']

    bootstrap, bootstrap_meta = fetch_json(base + 'bootstrap-static/')
    fixtures, fixtures_meta = fetch_json(base + 'fixtures/')

    raw_manifest: dict[str, Any] = {
        'provider': p,
        'bootstrap': bootstrap_meta,
        'fixtures': fixtures_meta,
        'profiles': [],
    }
    if isinstance(bootstrap, dict):
        (pdir / 'bootstrap-static.json').write_text(json.dumps(bootstrap, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if fixtures is not None:
        (pdir / 'fixtures.json').write_text(json.dumps(fixtures, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    elements = bootstrap.get('elements') if isinstance(bootstrap, dict) else None
    if not isinstance(elements, list) or not elements:
        raw_manifest['status'] = 'FAIL_CLOSED_NO_BOOTSTRAP_PLAYERS'
        (pdir / 'manifest.json').write_text(json.dumps(raw_manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return {
            'provider': p['provider'], 'competition': p['competition'], 'key': key,
            'status': raw_manifest['status'], 'player_count': 0,
            'profile_success': 0, 'profile_failures': 0, 'profile_success_rate': 0.0,
            'history_past_rows': 0,
            'bootstrap_http': bootstrap_meta.get('http_status'),
            'fixtures_http': fixtures_meta.get('http_status'),
        }

    ids = [e.get('id') for e in elements if e.get('id') is not None]
    current_rows = [compact_element(e) for e in elements]
    teams = bootstrap.get('teams') if isinstance(bootstrap.get('teams'), list) else []
    team_index = {t.get('id'): t for t in teams if isinstance(t, dict)}

    profiles: dict[str, Any] = {}
    metas: dict[str, Any] = {}

    def one(pid: Any):
        obj, meta = fetch_json(base + f'element-summary/{pid}/')
        return pid, obj, meta

    # Modest concurrency: fast enough for the runner, conservative for public providers.
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(one, pid) for pid in ids]
        for fut in as_completed(futs):
            pid, obj, meta = fut.result()
            metas[str(pid)] = meta
            if isinstance(obj, dict):
                profiles[str(pid)] = obj
                (pdir / 'players').mkdir(exist_ok=True)
                (pdir / 'players' / f'{pid}.json').write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            raw_manifest['profiles'].append({'player_id': pid, **meta, 'json_ok': isinstance(obj, dict)})

    success = len(profiles)
    failures = len(ids) - success
    success_rate = success / len(ids) if ids else 0.0

    history_past = []
    current_history = []
    for e in elements:
        pid = e.get('id')
        profile = profiles.get(str(pid)) or {}
        base_identity = {
            'provider': p['provider'],
            'competition': p['competition'],
            'provider_player_id': pid,
            'web_name': e.get('web_name'),
            'first_name': e.get('first_name'),
            'second_name': e.get('second_name'),
            'provider_team_id': e.get('team'),
            'provider_team_name': (team_index.get(e.get('team')) or {}).get('name'),
        }
        for row in profile.get('history_past') or []:
            if isinstance(row, dict):
                history_past.append({**base_identity, 'provider_history': row})
        for row in profile.get('history') or []:
            if isinstance(row, dict):
                current_history.append({**base_identity, 'provider_history': row})

    normalized = {
        'schema': 'NEXUS_FPL_CLONE_PROVIDER_NATIVE_V1',
        'provider': p,
        'current_elements': current_rows,
        'history_past': history_past,
        'current_history': current_history,
        'governance': {
            'provider_native_fields_preserved': True,
            'cross_provider_score_normalization': False,
            'fantasy_points_relabelled_as_fantacalcio': False,
            'missing_value_fill': False,
            'history_past_claimed_only_when_provider_returned': True,
        },
    }
    (pdir / 'normalized.json').write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    raw_manifest['status'] = 'PASS' if success_rate >= 0.95 else ('PARTIAL' if success else 'FAIL_CLOSED')
    (pdir / 'manifest.json').write_text(json.dumps(raw_manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    seasons = sorted({str(x['provider_history'].get('season_name') or x['provider_history'].get('season') or x['provider_history'].get('seasonName')) for x in history_past if x.get('provider_history')}, reverse=True)
    return {
        'provider': p['provider'],
        'competition': p['competition'],
        'key': key,
        'status': raw_manifest['status'],
        'player_count': len(ids),
        'profile_success': success,
        'profile_failures': failures,
        'profile_success_rate': round(success_rate, 4),
        'history_past_rows': len(history_past),
        'history_past_season_labels_observed': [s for s in seasons if s not in ('None','')],
        'current_history_rows': len(current_history),
        'bootstrap_http': bootstrap_meta.get('http_status'),
        'fixtures_http': fixtures_meta.get('http_status'),
    }


summaries = []
for provider in PROVIDERS:
    summaries.append(acquire_provider(provider))

summary = {
    'schema': 'NEXUS_FPL_CLONE_CROSSLEAGUE_ACQUISITION_V1_SUMMARY',
    'providers': summaries,
    'provider_count': len(summaries),
    'pass_count': sum(1 for x in summaries if x['status'] == 'PASS'),
    'status': 'PASS' if summaries and all(x['status'] == 'PASS' for x in summaries) else ('PARTIAL' if any(x['status'] == 'PASS' for x in summaries) else 'FAIL_CLOSED'),
    'governance': {
        'public_unauthenticated_reads_only': True,
        'raw_provider_payloads_preserved_in_artifact': True,
        'provider_native_history_past_preserved': True,
        'cross_provider_normalization': False,
        'fantacalcio_relabelling': False,
        'missing_value_fill': False,
        'predictive_models_modified': False,
        'decision_layer_started': False,
    },
}
(OUT / 'SUMMARY.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=2))
