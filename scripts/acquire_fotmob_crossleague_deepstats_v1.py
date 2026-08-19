#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import requests

SRC = Path('.nexus-fotmob-nextdata-career-v3-status/RESULT.json')
OUT = Path('/mnt/data/nexus-fotmob-crossleague-deepstats-v1')
OUT.mkdir(parents=True, exist_ok=True)
ENDPOINT = 'https://www.fotmob.com/api/data/playerStats'
CURRENT_SEASON = '2026/2027'
MAX_PRIOR_SEASONS = 5
HEADERS = {
    'User-Agent': 'Mozilla/5.0 FantaNexus research acquisition',
    'Accept': 'application/json,text/plain,*/*',
    'Referer': 'https://www.fotmob.com/',
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_stat_root(v, player_id):
    candidates = []
    def walk(x, path='$'):
        if isinstance(x, dict):
            if isinstance(x.get('statSeasons'), list):
                score = (10 if str(x.get('id')) == str(player_id) else 0) + (5 if 'firstSeasonStats' in x else 0)
                candidates.append((score, path, x))
            for k, z in x.items():
                if isinstance(z, (dict, list)):
                    walk(z, f'{path}.{k}')
        elif isinstance(x, list):
            for i, z in enumerate(x):
                if isinstance(z, (dict, list)):
                    walk(z, f'{path}[{i}]')
    walk(v)
    return max(candidates, key=lambda x: x[0]) if candidates else None


def flatten_options(root):
    rows = []
    idx = 0
    for season in root.get('statSeasons') or []:
        for t in season.get('tournaments') or []:
            rows.append({
                'provider_order': idx,
                'seasonName': season.get('seasonName'),
                'entryId': t.get('entryId'),
                'tournamentId': t.get('tournamentId'),
                'tournamentName': t.get('name') or t.get('tournamentName'),
                'hasDeepStats': t.get('hasDeepStats'),
            })
            idx += 1
    return rows


def select_prior(options):
    seasons = []
    for x in options:
        s = x.get('seasonName')
        if not s or s == CURRENT_SEASON:
            continue
        if s not in seasons:
            seasons.append(s)
        if len(seasons) >= MAX_PRIOR_SEASONS:
            break
    selected = [x for x in options if x.get('seasonName') in seasons]
    return seasons, selected


def stats_by_id(obj):
    out = {}
    def walk(x, path='$'):
        if isinstance(x, dict):
            sid = x.get('localizedTitleId')
            if sid and any(k in x for k in ['statValue', 'per90', 'percentileRank', 'title']):
                row = {
                    'title': x.get('title') or x.get('statTitle'),
                    'statValue': x.get('statValue'),
                    'per90': x.get('per90'),
                    'percentileRank': x.get('percentileRank'),
                    'percentileRankPer90': x.get('percentileRankPer90'),
                    'statFormat': x.get('statFormat'),
                    'path': path,
                }
                # Keep first leaf-like occurrence for a stat id; group headers have no value.
                prev = out.get(sid)
                if prev is None or (prev.get('statValue') is None and row.get('statValue') is not None):
                    out[sid] = row
            for k, z in x.items():
                if isinstance(z, (dict, list)):
                    walk(z, f'{path}.{k}')
        elif isinstance(x, list):
            for i, z in enumerate(x):
                if isinstance(z, (dict, list)):
                    walk(z, f'{path}[{i}]')
    walk(obj)
    return out


def observed_fields(stats):
    preferred = [
        'rating','matches_uppercase','player_started_matches','minutes_played',
        'goals','assists','expected_goals','expected_goals_on_target','non_penalty_xg',
        'shots','ShotsOnTarget','expected_assists','chances_created','big_chance_created_team_title',
        'yellow_cards','red_cards','fouls','fouls_won','touches','touches_opp_box',
        'successful_passes','successful_passes_accuracy','dribbles_succeeded','duel_won','aerials_won',
        'recoveries','interceptions','matchstats.headers.tackles','clearances','blocked_shots',
    ]
    return {k: stats[k] for k in preferred if k in stats and stats[k].get('statValue') is not None}


source = json.loads(SRC.read_text(encoding='utf-8'))
raw_records = []
normalized = []
coverage = []
players_summary = []

for player in source.get('players', []):
    name, pid = player.get('name'), player.get('id')
    root_hit = find_stat_root(player, pid)
    ps = {'name': name, 'playerId': pid, 'status': None, 'season_count': 0, 'records': 0, 'failures': 0}
    if not root_hit:
        ps['status'] = 'FAIL_CLOSED_NO_STATSEASONS'
        players_summary.append(ps)
        continue
    _, root_path, root = root_hit
    options = flatten_options(root)
    seasons, selected = select_prior(options)
    ps['selected_seasons'] = seasons
    ps['season_count'] = len(seasons)
    for opt in selected:
        meta = {
            'player_name': name,
            'player_id': pid,
            'season': opt.get('seasonName'),
            'tournament_name': opt.get('tournamentName'),
            'tournament_id': opt.get('tournamentId'),
            'entry_id': opt.get('entryId'),
            'hasDeepStats': opt.get('hasDeepStats'),
            'provider': 'FotMob',
        }
        obj = None
        transport = {}
        # The frontend embeds the first provider option as firstSeasonStats and does not request it.
        if opt.get('provider_order') == 0 and root.get('firstSeasonStats') is not None:
            obj = root.get('firstSeasonStats')
            raw_bytes = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str).encode('utf-8')
            transport = {
                'source': 'embedded_firstSeasonStats',
                'http_status': None,
                'bytes': len(raw_bytes),
                'sha256': sha256(raw_bytes),
            }
        else:
            params = {'playerId': str(pid), 'seasonId': str(opt.get('entryId')), 'isFirstSeason': 'false'}
            try:
                r = requests.get(ENDPOINT, params=params, headers=HEADERS, timeout=(8, 30), allow_redirects=True)
                raw = r.content
                transport = {
                    'source': 'api_playerStats',
                    'request_url': r.url,
                    'http_status': r.status_code,
                    'content_type': r.headers.get('content-type', ''),
                    'bytes': len(raw),
                    'sha256': sha256(raw),
                }
                try:
                    obj = r.json()
                except Exception as e:
                    transport['json_error'] = repr(e)
            except Exception as e:
                transport = {'source': 'api_playerStats', 'request_error': repr(e)}
            time.sleep(0.25)

        rec = {**meta, 'transport': transport, 'raw': obj}
        raw_records.append(rec)
        if isinstance(obj, dict):
            stats = stats_by_id(obj)
            observed = observed_fields(stats)
            norm = {
                **meta,
                'claim_status': 'OBSERVED',
                'provider_rating': (stats.get('rating') or {}).get('statValue'),
                'official_fantasy_points': None,
                'stats_by_id': stats,
                'observed_priority_fields': observed,
                'shotmap_count': len(obj.get('shotmap') or []),
                'response_keys': list(obj.keys()),
            }
            normalized.append(norm)
            coverage.append({
                **meta,
                'status': 'OBSERVED',
                'available_stat_ids': sorted(k for k, v in stats.items() if v.get('statValue') is not None),
                'shotmap_available': isinstance(obj.get('shotmap'), list),
            })
            ps['records'] += 1
        else:
            coverage.append({**meta, 'status': 'UNAVAILABLE', 'reason': transport})
            ps['failures'] += 1
    ps['status'] = 'PASS' if ps['records'] and ps['failures'] == 0 else ('PARTIAL' if ps['records'] else 'FAIL_CLOSED')
    players_summary.append(ps)

result = {
    'schema': 'NEXUS_FOTMOB_CROSSLEAGUE_DEEPSTATS_V1',
    'current_season_excluded': CURRENT_SEASON,
    'max_prior_seasons': MAX_PRIOR_SEASONS,
    'players': players_summary,
    'records': raw_records,
    'governance': {
        'provider': 'FotMob',
        'public_unauthenticated_surfaces_only': True,
        'only_observed_player_and_season_ids_used': True,
        'raw_provider_data_preserved': True,
        'provider_rating_separate_from_official_fantasy_points': True,
        'missing_fields_not_imputed': True,
        'predictive_models_modified': False,
        'decision_layer_started': False,
    },
}
summary = {
    'schema': 'NEXUS_FOTMOB_CROSSLEAGUE_DEEPSTATS_V1_SUMMARY',
    'current_season_excluded': CURRENT_SEASON,
    'max_prior_seasons': MAX_PRIOR_SEASONS,
    'players': players_summary,
    'record_count': len(raw_records),
    'observed_record_count': len(normalized),
    'unavailable_record_count': sum(1 for x in coverage if x.get('status') != 'OBSERVED'),
    'status': 'PASS' if players_summary and all(x.get('status') == 'PASS' for x in players_summary) else 'PARTIAL',
    'governance': result['governance'],
}

(OUT / 'RAW.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
(OUT / 'NORMALIZED.json').write_text(json.dumps({'schema':'NEXUS_FOTMOB_CROSSLEAGUE_DEEPSTATS_V1_NORMALIZED','records':normalized}, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
(OUT / 'COVERAGE.json').write_text(json.dumps({'schema':'NEXUS_FOTMOB_CROSSLEAGUE_DEEPSTATS_V1_COVERAGE','records':coverage}, ensure_ascii=False, indent=2, default=str) + '\n', encoding='utf-8')
(OUT / 'SUMMARY.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=2))
