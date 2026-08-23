#!/usr/bin/env python3
import codecs
import csv
import hashlib
import io
import json
import re
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "NEXUS_F2_UNDERSTAT_PLAYER_MATCH_TEMPORAL_PROBE_V1"
OUT = Path(".nexus-f2-understat-player-match-temporal-probe-v1")
RAW = OUT / "raw"
UNDERSTAT_COMMIT = "768b7ca0b977a5e6b4b429c7b0cf750e8269f2fc"
UNDERSTAT_SHA256 = "b78fad5f01844a0fdab0d89474dafba9b86c586d2f0ce88f0ce2c9af70d2bc64"
CSV_URL = f"https://raw.githubusercontent.com/vibedatascience/understat_players_aggregated/{UNDERSTAT_COMMIT}/understat_players_aggregated_2014_2024.csv"
PLAYER_URL = "https://understat.com/player/{player_id}"
USER_AGENT = "Mozilla/5.0 (compatible; FantaNexus-F2-Temporal-Probe/1.0; research-audit)"

# Exact F1/D1-bound IDs, deterministic 2-per-Classic-Role cohort with long Serie A histories.
COHORT = [
    {"playerId": "1305", "name": "Lukasz Skorupski", "classicRole": "P"},
    {"playerId": "1093", "name": "Mattia Perin", "classicRole": "P"},
    {"playerId": "1541", "name": "Stefan de Vrij", "classicRole": "D"},
    {"playerId": "1463", "name": "Francesco Acerbi", "classicRole": "D"},
    {"playerId": "1471", "name": "Lorenzo Pellegrini", "classicRole": "C"},
    {"playerId": "1122", "name": "Manuel Locatelli", "classicRole": "C"},
    {"playerId": "1294", "name": "Paulo Dybala", "classicRole": "A"},
    {"playerId": "1612", "name": "Domenico Berardi", "classicRole": "A"}
]

OBSERVED_RECONCILE = {
    "games": "COUNT_MATCH_ROWS",
    "time": "SUM_INT",
    "goals": "SUM_INT",
    "npg": "SUM_INT",
    "assists": "SUM_INT",
    "shots": "SUM_INT",
    "key_passes": "SUM_INT"
}
EXPECTED_MODEL_FIELDS = ["xG", "npxG", "xA", "xGChain", "xGBuildup"]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str, timeout=90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {url}")
        return response.read()


def parse_matches_data(html: str):
    # Understat embeds JSON as JSON.parse('...') with escaped bytes.
    patterns = [
        r"var\s+matchesData\s*=\s*JSON\.parse\('(.+?)'\);",
        r"matchesData\s*=\s*JSON\.parse\('(.+?)'\);"
    ]
    encoded = None
    for pattern in patterns:
        match = re.search(pattern, html, flags=re.DOTALL)
        if match:
            encoded = match.group(1)
            break
    if encoded is None:
        raise RuntimeError("matchesData JSON.parse payload not found")
    try:
        decoded = codecs.escape_decode(encoded.encode("utf-8"))[0].decode("utf-8")
    except Exception:
        decoded = bytes(encoded, "utf-8").decode("unicode_escape")
    payload = json.loads(decoded)
    if isinstance(payload, dict):
        matches = payload.get("matches")
    else:
        matches = payload
    if not isinstance(matches, list):
        raise RuntimeError(f"matchesData shape invalid: {type(payload).__name__}")
    return matches


def to_int(value, field, player_id, season):
    try:
        return int(float(value))
    except Exception as exc:
        raise RuntimeError(f"Non-integer observed field {field}={value!r} for player={player_id} season={season}") from exc


def source_season_label(raw):
    year = int(str(raw))
    return f"{year}/{str(year + 1)[-2:]}"


def match_aggregate(rows, player_id, season):
    if not rows:
        return None
    dates = []
    out = {"games": len(rows), "time": 0, "goals": 0, "npg": 0, "assists": 0, "shots": 0, "key_passes": 0}
    clubs = set()
    match_ids = set()
    for r in rows:
        date = str(r.get("date") or "").split()[0]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise RuntimeError(f"Missing/invalid match date for player={player_id} season={season}: {r.get('date')!r}")
        datetime.strptime(date, "%Y-%m-%d")
        dates.append(date)
        mid = str(r.get("id") or "")
        if not mid or mid in match_ids:
            raise RuntimeError(f"Missing/duplicate match id for player={player_id} season={season}: {mid!r}")
        match_ids.add(mid)
        for f in ["time", "goals", "npg", "assists", "shots", "key_passes"]:
            out[f] += to_int(r.get(f, 0), f, player_id, season)
        for team_field in ["h_team", "a_team"]:
            if r.get(team_field):
                clubs.add(str(r[team_field]))
    out["firstMatchDate"] = min(dates)
    out["lastMatchDate"] = max(dates)
    out["matchIdsSha256"] = hashlib.sha256("\n".join(sorted(match_ids)).encode()).hexdigest()
    out["observedMatchTeams"] = sorted(clubs)
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    csv_raw = fetch(CSV_URL)
    if sha256_bytes(csv_raw) != UNDERSTAT_SHA256:
        raise SystemExit("FAIL: pinned Understat CSV SHA256 mismatch")
    (RAW / "pinned-source.sha256.txt").write_text(f"{UNDERSTAT_SHA256}  understat_players_aggregated_2014_2024.csv\n", encoding="utf-8")

    cohort_ids = {x["playerId"] for x in COHORT}
    reader = csv.DictReader(io.StringIO(csv_raw.decode("utf-8-sig")))
    source_rows = defaultdict(list)
    for row in reader:
        pid = str(row.get("id") or "")
        if pid not in cohort_ids or row.get("league") != "Serie_A":
            continue
        season = source_season_label(row["season"])
        source_rows[(pid, season)].append(row)

    player_evidence = []
    reconciliation = []
    failures = []
    total_match_rows = 0
    dated_match_rows = 0

    for idx, subject in enumerate(COHORT):
        pid = subject["playerId"]
        if idx:
            time.sleep(1.0)
        html_raw = fetch(PLAYER_URL.format(player_id=pid))
        html_sha = sha256_bytes(html_raw)
        html_path = RAW / f"player-{pid}.html"
        html_path.write_bytes(html_raw)
        matches = parse_matches_data(html_raw.decode("utf-8", errors="replace"))
        total_match_rows += len(matches)
        dated_match_rows += sum(1 for r in matches if re.match(r"^\d{4}-\d{2}-\d{2}", str(r.get("date") or "")))
        raw_matches = (json.dumps(matches, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        matches_path = RAW / f"player-{pid}-matches.json"
        matches_path.write_bytes(raw_matches)

        by_season = defaultdict(list)
        for row in matches:
            if row.get("season") is None:
                failures.append({"playerId": pid, "code": "MATCH_ROW_SEASON_MISSING", "matchId": row.get("id")})
                continue
            season = source_season_label(row["season"])
            by_season[season].append(row)

        source_for_player = sorted((season, rows) for (source_pid, season), rows in source_rows.items() if source_pid == pid)
        player_evidence.append({
            **subject,
            "htmlBytes": len(html_raw),
            "htmlSha256": html_sha,
            "matchesRows": len(matches),
            "matchesPayloadSha256": sha256_bytes(raw_matches),
            "sourceSerieASeasonRows": len(source_for_player),
            "matchSeasonCount": len(by_season)
        })

        for season, rows in source_for_player:
            if len(rows) != 1:
                failures.append({"playerId": pid, "season": season, "code": "PINNED_SOURCE_DUPLICATE_PLAYER_LEAGUE_SEASON", "rows": len(rows)})
                continue
            src = rows[0]
            match_rows = by_season.get(season, [])
            if not match_rows:
                failures.append({"playerId": pid, "season": season, "code": "NO_MATCH_LEVEL_ROWS_FOR_PINNED_SOURCE_SEASON"})
                continue
            agg = match_aggregate(match_rows, pid, season)
            field_results = {}
            all_equal = True
            for field in OBSERVED_RECONCILE:
                src_value = to_int(src[field], field, pid, season)
                match_value = agg[field]
                equal = src_value == match_value
                field_results[field] = {"sourceAggregate": src_value, "matchReconstruction": match_value, "equal": equal}
                all_equal = all_equal and equal
            rec = {
                "playerId": pid,
                "playerName": subject["name"],
                "classicRole": subject["classicRole"],
                "season": season,
                "sourceTeamTitle": src.get("team_title"),
                "sourceTeamTitleMultiClub": "," in str(src.get("team_title") or ""),
                "firstMatchDate": agg["firstMatchDate"],
                "lastMatchDate": agg["lastMatchDate"],
                "matchCount": len(match_rows),
                "fieldResults": field_results,
                "allObservedFieldsExact": all_equal
            }
            reconciliation.append(rec)
            if not all_equal:
                failures.append({"playerId": pid, "season": season, "code": "OBSERVED_FIELD_RECONCILIATION_MISMATCH", "fieldResults": field_results})

    role_counts = defaultdict(int)
    for x in COHORT:
        role_counts[x["classicRole"]] += 1
    exact_seasons = sum(1 for r in reconciliation if r["allObservedFieldsExact"])
    report = {
        "schema": SCHEMA,
        "status": "PASS" if not failures and reconciliation else "FAIL",
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "provider": "UNDERSTAT",
            "playerPage": "https://understat.com/player/{player_id}",
            "pinnedAggregateRepository": "vibedatascience/understat_players_aggregated",
            "pinnedAggregateCommit": UNDERSTAT_COMMIT,
            "pinnedAggregateSha256": UNDERSTAT_SHA256
        },
        "cohort": {
            "selection": "DETERMINISTIC_EXACT_F1_D1_BOUND_LONG_HISTORY_TWO_PER_CLASSIC_ROLE",
            "players": len(COHORT),
            "classicRoleCounts": dict(sorted(role_counts.items()))
        },
        "observedMatchShape": {
            "totalMatchRows": total_match_rows,
            "datedMatchRows": dated_match_rows,
            "allMatchRowsDated": total_match_rows == dated_match_rows,
            "requiredFields": ["season", "date", "id", "time", "goals", "npg", "assists", "shots", "key_passes"]
        },
        "reconciliation": {
            "playerLeagueSeasonComparisons": len(reconciliation),
            "exactObservedFieldComparisons": exact_seasons,
            "allComparedSeasonsExact": len(reconciliation) == exact_seasons and len(reconciliation) > 0,
            "fields": list(OBSERVED_RECONCILE.keys()),
            "rows": reconciliation
        },
        "temporalInterpretation": {
            "observedEventStableFields": "CANDIDATE_FOR_F1_RELEASE_CONDITION_IF_FULL_EXACT_D1_UNIVERSE_RECONSTRUCTION_PASSES",
            "historicalEventDatePresent": total_match_rows == dated_match_rows and total_match_rows > 0,
            "expectedModelFields": EXPECTED_MODEL_FIELDS,
            "expectedModelFieldsReleased": False,
            "reason": "Historical match dates do not prove provider-model expected-metric vintage or invariance."
        },
        "playerEvidence": player_evidence,
        "failures": failures,
        "governance": {
            "newProviderIntroduced": False,
            "fuzzyMatchingUsed": False,
            "expectedMetricsPromoted": False,
            "f2ParametersFitted": False,
            "canonicalPredictiveEngineModified": False
        }
    }
    report_raw = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (OUT / "PROBE.json").write_bytes(report_raw)
    manifest = {
        "schema": "NEXUS_F2_UNDERSTAT_PLAYER_MATCH_TEMPORAL_PROBE_MANIFEST_V1",
        "status": report["status"],
        "probeSha256": sha256_bytes(report_raw),
        "rawFiles": [
            {"path": str(p.relative_to(OUT)), "bytes": p.stat().st_size, "sha256": sha256_bytes(p.read_bytes())}
            for p in sorted(RAW.iterdir()) if p.is_file()
        ]
    }
    manifest_raw = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (OUT / "MANIFEST.json").write_bytes(manifest_raw)
    print(json.dumps({
        "status": report["status"],
        "players": len(COHORT),
        "matchRows": total_match_rows,
        "comparisons": len(reconciliation),
        "exactComparisons": exact_seasons,
        "failureCount": len(failures),
        "probeSha256": sha256_bytes(report_raw),
        "manifestSha256": sha256_bytes(manifest_raw)
    }, indent=2))
    if report["status"] != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
