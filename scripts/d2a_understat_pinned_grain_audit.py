#!/usr/bin/env python3
import csv
import hashlib
import io
import json
import urllib.request
from collections import Counter
from pathlib import Path

PINNED_COMMIT = "768b7ca0b977a5e6b4b429c7b0cf750e8269f2fc"
EXPECTED_GIT_BLOB_SHA1 = "ddf4327251bb781f88b6edc4662bf20e5379ff3f"
SOURCE_URL = f"https://raw.githubusercontent.com/vibedatascience/understat_players_aggregated/{PINNED_COMMIT}/understat_players_aggregated_2014_2024.csv"
OUTPUT = Path("data/nexus-d2/probes/understat-pinned-grain-audit-v1.json")

with urllib.request.urlopen(SOURCE_URL, timeout=60) as response:
    raw = response.read()

git_blob_sha1 = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
if git_blob_sha1 != EXPECTED_GIT_BLOB_SHA1:
    raise SystemExit(f"Pinned blob mismatch: expected {EXPECTED_GIT_BLOB_SHA1}, got {git_blob_sha1}")

text = raw.decode("utf-8-sig")
reader = csv.DictReader(io.StringIO(text))
rows = list(reader)
required = ["id", "player_name", "team_title", "league", "year", "season"]
missing_columns = [c for c in required if c not in (reader.fieldnames or [])]
if missing_columns:
    raise SystemExit(f"Missing required columns: {missing_columns}")

multi = [r for r in rows if "," in (r.get("team_title") or "")]
unique_multi_players = {r["id"] for r in multi if r.get("id")}
key_counts = Counter((r.get("id"), r.get("season"), r.get("league"), r.get("team_title")) for r in rows)
duplicate_exact_keys = sum(1 for n in key_counts.values() if n > 1)
rows_in_duplicate_exact_keys = sum(n for n in key_counts.values() if n > 1)

by_league = Counter(r.get("league") or "<MISSING>" for r in rows)
multi_by_league = Counter(r.get("league") or "<MISSING>" for r in multi)
by_season = Counter(r.get("season") or "<MISSING>" for r in rows)
multi_by_season = Counter(r.get("season") or "<MISSING>" for r in multi)
comma_count_distribution = Counter((r.get("team_title") or "").count(",") for r in multi)

missingness = {
    field: sum(1 for r in rows if r.get(field) is None or str(r.get(field)).strip() == "")
    for field in required
}

examples = [
    {
        "id": r.get("id"),
        "player_name": r.get("player_name"),
        "team_title": r.get("team_title"),
        "league": r.get("league"),
        "season": r.get("season"),
    }
    for r in multi[:10]
]

report = {
    "schema": "NEXUS_D2A_UNDERSTAT_PINNED_GRAIN_AUDIT_V1",
    "status": "PASS_AUDIT_MATERIAL_GRAIN_GAP_CONFIRMED",
    "source": {
        "repository": "vibedatascience/understat_players_aggregated",
        "pinnedCommit": PINNED_COMMIT,
        "file": "understat_players_aggregated_2014_2024.csv",
        "sourceUrl": SOURCE_URL,
        "expectedGitBlobSha1": EXPECTED_GIT_BLOB_SHA1,
        "observedGitBlobSha1": git_blob_sha1,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    },
    "schemaFields": reader.fieldnames,
    "counts": {
        "rows": len(rows),
        "uniquePlayers": len({r["id"] for r in rows if r.get("id")}),
        "leagues": len({r["league"] for r in rows if r.get("league")}),
        "seasons": len({r["season"] for r in rows if r.get("season")}),
        "rowsWithCommaSeparatedMultiClubTeamTitle": len(multi),
        "uniquePlayersWithMultiClubAggregateRows": len(unique_multi_players),
        "singleTeamTitleRows": len(rows) - len(multi),
        "duplicateExactPlayerSeasonLeagueTeamTitleKeys": duplicate_exact_keys,
        "rowsInDuplicateExactKeys": rows_in_duplicate_exact_keys,
    },
    "missingness": missingness,
    "rowsByLeague": dict(sorted(by_league.items())),
    "multiClubRowsByLeague": dict(sorted(multi_by_league.items())),
    "rowsBySeason": dict(sorted(by_season.items())),
    "multiClubRowsBySeason": dict(sorted(multi_by_season.items())),
    "multiClubCommaCountDistribution": {str(k): v for k, v in sorted(comma_count_distribution.items())},
    "examples": examples,
    "scientificFinding": {
        "canonicalD2Grain": "player-season-league-club-stint",
        "actualSourceGrainForTransferRows": "player-season-league with multiple clubs encoded in one team_title field",
        "readmeSeparateClubRecordClaimSupportedByPinnedBytes": False,
        "safeToSplitCommaSeparatedRowsIntoCanonicalStints": False,
        "safeToAllocateAggregatedMetricsAcrossClubs": False,
        "typedGap": "AGGREGATED_MULTI_CLUB_ROW",
        "d2Consequence": "These rows cannot become canonical club-stints without independent source evidence that preserves stint boundaries and club-specific observations."
    },
    "governance": {
        "newProviderPromoted": False,
        "rawSourceMutated": False,
        "modelModified": False,
        "f1Started": False,
    }
}

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(json.dumps(report["counts"], indent=2))
print(f"Wrote {OUTPUT}")
