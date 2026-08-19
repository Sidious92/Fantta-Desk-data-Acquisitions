#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

SRC = Path('.nexus-fotmob-crossleague-deepstats-v1-status/NORMALIZED.json')
OUT = Path('/mnt/data/nexus-fotmob-crossleague-deepstats-v1-audit')
OUT.mkdir(parents=True, exist_ok=True)

PRIORITY = [
    'rating','matches_uppercase','player_started_matches','minutes_played',
    'goals','assists','shots','ShotsOnTarget','expected_goals','non_penalty_xg',
    'expected_assists','chances_created','yellow_cards','red_cards'
]
obj = json.loads(SRC.read_text(encoding='utf-8'))
records = obj.get('records', [])

def has_value(rec, stat):
    x = (rec.get('stats_by_id') or {}).get(stat)
    return isinstance(x, dict) and x.get('statValue') is not None

by_tournament = defaultdict(list)
by_player = defaultdict(list)
for r in records:
    key = (r.get('tournament_id'), r.get('tournament_name'))
    by_tournament[key].append(r)
    by_player[(r.get('player_id'), r.get('player_name'))].append(r)


def summarize(group):
    n = len(group)
    cov = {}
    for stat in PRIORITY:
        k = sum(1 for r in group if has_value(r, stat))
        cov[stat] = {'observed': k, 'records': n, 'coverage': round(k / n, 4) if n else None}
    return cov

tournaments = []
for (tid, name), rs in sorted(by_tournament.items(), key=lambda kv: (str(kv[0][1]), str(kv[0][0]))):
    tournaments.append({
        'tournament_id': tid,
        'tournament_name': name,
        'competition_classification': 'UNVERIFIED',
        'records': len(rs),
        'players': sorted(set(r.get('player_name') for r in rs)),
        'seasons': sorted(set(r.get('season') for r in rs), reverse=True),
        'priority_field_coverage': summarize(rs),
    })
players = []
for (pid, name), rs in sorted(by_player.items(), key=lambda kv: str(kv[0][1])):
    players.append({
        'player_id': pid,
        'player_name': name,
        'records': len(rs),
        'seasons': sorted(set(r.get('season') for r in rs), reverse=True),
        'priority_field_coverage': summarize(rs),
    })
summary = {
    'schema': 'NEXUS_FOTMOB_CROSSLEAGUE_DEEPSTATS_V1_AUDIT',
    'record_count': len(records),
    'priority_fields': PRIORITY,
    'overall_coverage': summarize(records),
    'players': players,
    'tournaments': tournaments,
    'interpretation_rules': {
        'competition_type_not_inferred_from_name': True,
        'chances_created_not_relabelled_as_key_passes': True,
        'rating_is_provider_rating_not_fantasy_vote': True,
        'missing_values_not_imputed': True,
    },
}
(OUT / 'AUDIT.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=2))
