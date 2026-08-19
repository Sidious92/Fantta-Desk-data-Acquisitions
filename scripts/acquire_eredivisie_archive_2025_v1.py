#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path

SRC = Path(os.environ.get('EREDIVISIE_ARCHIVE_SRC', '/tmp/eredivisie/data/2025'))
OUT = Path('/mnt/data/nexus-eredivisie-archive-2025-v1')
RAW = OUT / 'raw' / 'data' / '2025'
OUT.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

if not SRC.exists():
    raise SystemExit(f'archive source missing: {SRC}')

if RAW.exists():
    shutil.rmtree(RAW)
shutil.copytree(SRC, RAW)

files = []
for p in sorted(RAW.rglob('*')):
    if p.is_file():
        files.append({
            'path': str(p.relative_to(RAW)),
            'bytes': p.stat().st_size,
            'sha256': sha256_file(p),
        })

bootstrap_path = RAW / 'eredivisie-bootstrap_2025.json'
bootstrap = json.loads(bootstrap_path.read_text(encoding='utf-8')) if bootstrap_path.exists() else None
elements = bootstrap.get('elements') if isinstance(bootstrap, dict) else None
teams = bootstrap.get('teams') if isinstance(bootstrap, dict) else None
players_dir = RAW / 'players'
gameweeks_dir = RAW / 'gameweeks'
csv_dir = RAW / 'csv'
player_files = list(players_dir.glob('*.json')) if players_dir.exists() else []
gameweek_files = list(gameweeks_dir.glob('*.json')) if gameweeks_dir.exists() else []
csv_files = list(csv_dir.glob('*.csv')) if csv_dir.exists() else []

repo_commit = os.environ.get('EREDIVISIE_ARCHIVE_COMMIT')
validation = {
    'bootstrap_exists': bootstrap_path.exists(),
    'bootstrap_player_count': len(elements) if isinstance(elements, list) else 0,
    'bootstrap_team_count': len(teams) if isinstance(teams, list) else 0,
    'players_directory_exists': players_dir.exists(),
    'player_json_count': len(player_files),
    'gameweeks_directory_exists': gameweeks_dir.exists(),
    'gameweek_json_count': len(gameweek_files),
    'csv_directory_exists': csv_dir.exists(),
    'csv_count': len(csv_files),
}
status = 'PASS' if (
    validation['bootstrap_player_count'] > 0
    and validation['players_directory_exists']
    and validation['player_json_count'] > 0
    and validation['gameweeks_directory_exists']
    and validation['gameweek_json_count'] > 0
) else 'FAIL_CLOSED'

summary = {
    'schema': 'NEXUS_EREDIVISIE_ARCHIVE_2025_ACQUISITION_V1_SUMMARY',
    'status': status,
    'provider': 'ESPN Fantasy Voetbal',
    'competition': 'Eredivisie',
    'season': '2025-26',
    'source_repository': 'TopMarx/eredivisie',
    'source_path': 'data/2025',
    'source_commit': repo_commit,
    'file_count': len(files),
    'total_bytes': sum(x['bytes'] for x in files),
    'validation': validation,
    'governance': {
        'raw_archive_preserved': True,
        'archive_season_kept_separate': True,
        'current_snapshot_overwritten': False,
        'cross_provider_normalization': False,
        'missing_value_fill': False,
        'predictive_models_modified': False,
        'decision_layer_started': False,
    },
}
(OUT / 'INVENTORY.json').write_text(json.dumps({'schema':'NEXUS_EREDIVISIE_ARCHIVE_2025_FILE_INVENTORY_V1','files':files}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
(OUT / 'SUMMARY.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False, indent=2))
if status != 'PASS':
    raise SystemExit(2)
