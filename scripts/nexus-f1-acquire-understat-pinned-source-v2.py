#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import pathlib
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

PINNED_COMMIT = "768b7ca0b977a5e6b4b429c7b0cf750e8269f2fc"
SOURCE_REPOSITORY = "vibedatascience/understat_players_aggregated"
SOURCE_FILE = "understat_players_aggregated_2014_2024.csv"
SOURCE_URL = f"https://raw.githubusercontent.com/{SOURCE_REPOSITORY}/{PINNED_COMMIT}/{SOURCE_FILE}"
OUTPUT_ROOT = pathlib.Path(os.environ.get("NEXUS_F1_UNDERSTAT_PINNED_OUTPUT", ".nexus-f1-understat-pinned-v2"))
TARGET_YEARS = tuple(range(2014, 2025))
REQUIRED_COLUMNS = {
    "id", "player_name", "team_title", "league", "year", "season", "games", "time",
    "goals", "npg", "assists", "shots", "key_passes", "xG", "npxG", "xA",
    "xGChain", "xGBuildup", "scrape_timestamp"
}
OBSERVED_REPLAY_CANDIDATES = ["games", "time", "goals", "npg", "assists", "shots", "key_passes"]
EXPECTED_REPLAY_QUARANTINED = ["xG", "npxG", "xA", "xGChain", "xGBuildup"]


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def fail(message: str) -> None:
    raise RuntimeError(f"Nexus F1 Understat pinned source v2: {message}")


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def season_label(year: int) -> str:
    return f"{year}/{str(year + 1)[-2:]}"


def number(value: str | None, field: str):
    if value is None or value == "":
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise RuntimeError(f"{field}: non-numeric {value!r}") from exc
    if parsed < 0:
        fail(f"{field}: negative value")
    if field in {"games", "time", "goals", "npg", "assists", "shots", "key_passes"} and parsed.is_integer():
        return int(parsed)
    return parsed


def obs(field: str, value: str | None, unit: str, semantics: str):
    parsed = number(value, field)
    return {
        "sourceField": field,
        "value": parsed,
        "unit": unit,
        "semantics": semantics,
        "transformation": "NONE",
        "missingReason": None if parsed is not None else "UNKNOWN",
    }


def missing(field: str, unit: str, semantics: str):
    return {
        "sourceField": field,
        "value": None,
        "unit": unit,
        "semantics": semantics,
        "transformation": "NONE",
        "missingReason": "NOT_COLLECTED",
    }


def split_source_club_label(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def download() -> tuple[bytes, str]:
    req = urllib.request.Request(
        SOURCE_URL,
        headers={
            "User-Agent": "FantaNexus-F1-RAW/1.1 (noncommercial research acquisition)",
            "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1",
        },
    )
    captured_at = iso_now()
    with urllib.request.urlopen(req, timeout=60) as response:
        if response.status != 200:
            fail(f"HTTP {response.status}")
        raw = response.read()
    if not raw:
        fail("empty source")
    return raw, captured_at


def main() -> None:
    raw_root = OUTPUT_ROOT / "raw"
    normalized_root = OUTPUT_ROOT / "normalized"
    raw_root.mkdir(parents=True, exist_ok=True)
    normalized_root.mkdir(parents=True, exist_ok=True)

    raw, captured_at = download()
    source_sha = sha256(raw)
    (raw_root / SOURCE_FILE).write_bytes(raw)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames is None:
        fail("missing CSV header")
    missing_columns = sorted(REQUIRED_COLUMNS.difference(reader.fieldnames))
    if missing_columns:
        fail(f"missing columns {missing_columns}")

    rows = []
    for csv_row, row in enumerate(reader, start=2):
        if row.get("league") != "Serie_A":
            continue
        try:
            year = int(row.get("year", ""))
        except ValueError as exc:
            raise RuntimeError(f"row {csv_row}: invalid year") from exc
        if year not in TARGET_YEARS:
            continue
        if row.get("season") != season_label(year):
            fail(f"row {csv_row}: season/year mismatch")
        if not row.get("id") or not row.get("player_name") or not row.get("team_title"):
            fail(f"row {csv_row}: identity/club missing")
        rows.append((csv_row, year, row))

    if sorted({year for _, year, _ in rows}) != list(TARGET_YEARS):
        fail("target year coverage incomplete")

    grouped: dict[tuple[str, int], list[tuple[int, dict[str, str]]]] = defaultdict(list)
    for csv_row, year, row in rows:
        grouped[(str(row["id"]), year)].append((csv_row, row))

    source_version = f"PINNED_GIT:{SOURCE_REPOSITORY}@{PINNED_COMMIT}:{SOURCE_FILE}@sha256:{source_sha}"
    records = []
    technical_keys = set()
    source_row_hashes = set()
    by_season = Counter()
    missing_reasons = Counter()
    source_multi_club_aggregate_rows = 0
    separate_multi_row_player_seasons = 0
    stint_unresolved_records = 0
    single_club_records = 0
    raw_multi_club_labels = []

    for (player_id, year), player_rows in sorted(grouped.items(), key=lambda item: (item[0][1], item[0][0])):
        row_count_multi = len(player_rows) > 1
        if row_count_multi:
            separate_multi_row_player_seasons += 1
        for csv_row, row in sorted(player_rows, key=lambda item: item[0]):
            season = row["season"]
            raw_club_label = row["team_title"].strip()
            club_parts = split_source_club_label(raw_club_label)
            aggregate_multi = len(club_parts) > 1
            if aggregate_multi:
                source_multi_club_aggregate_rows += 1
                raw_multi_club_labels.append({
                    "season": season,
                    "sourcePlayerId": player_id,
                    "playerName": row["player_name"],
                    "sourceClubAggregate": raw_club_label,
                    "parsedClubLabels": club_parts,
                })

            row_payload = {key: row.get(key) for key in reader.fieldnames}
            row_sha = sha256(json.dumps(row_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if row_sha in source_row_hashes:
                fail(f"duplicate source row {row_sha}")
            source_row_hashes.add(row_sha)

            record_id = f"pinned-csv:{year}:{player_id}:row:{csv_row}"
            technical = ("UNDERSTAT", "SERIE_A", record_id, source_version)
            if technical in technical_keys:
                fail(f"duplicate technical key {technical}")
            technical_keys.add(technical)

            unambiguous_single_club = not aggregate_multi and not row_count_multi and len(club_parts) == 1
            analytic_club = club_parts[0] if unambiguous_single_club else (club_parts[0] if row_count_multi and len(club_parts) == 1 else None)
            quarantine = ["MAPPING_UNRESOLVED", "TEMPORAL_UNVERIFIED"]
            stint_id = None
            stint_ordinal = None
            if unambiguous_single_club:
                club_digest = hashlib.sha256(analytic_club.encode("utf-8")).hexdigest()[:16]
                stint_ordinal = 1
                stint_id = f"understat-pinned:{season}:{player_id}:1:{club_digest}"
                single_club_records += 1
            else:
                quarantine.append("STINT_UNRESOLVED")
                stint_unresolved_records += 1
                if aggregate_multi:
                    quarantine.append("SOURCE_AGGREGATE_MULTI_CLUB")

            observations = {
                "appearances": obs("games", row.get("games"), "count", "Understat-derived source aggregate games"),
                "starts": missing("starts", "count", "Not supplied by pinned Understat aggregate source"),
                "substituteAppearances": missing("substitute_appearances", "count", "Not supplied by pinned Understat aggregate source"),
                "minutes": obs("time", row.get("time"), "minutes", "Understat-derived source aggregate minutes"),
                "goals": obs("goals", row.get("goals"), "count", "Understat goals convention"),
                "nonPenaltyGoals": obs("npg", row.get("npg"), "count", "Understat non-penalty goals convention"),
                "assists": obs("assists", row.get("assists"), "count", "Understat assists convention"),
                "xG": obs("xG", row.get("xG"), "expected-goals units", "Understat xG; historical replay quarantined pending vintage/invariance proof"),
                "npxG": obs("npxG", row.get("npxG"), "expected-goals units", "Understat npxG; historical replay quarantined pending vintage/invariance proof"),
                "xA": obs("xA", row.get("xA"), "expected-assist units", "Understat xA; historical replay quarantined pending vintage/invariance proof"),
                "shots": obs("shots", row.get("shots"), "count", "Understat shots"),
                "keyPasses": obs("key_passes", row.get("key_passes"), "count", "Understat key passes"),
                "xGChain": obs("xGChain", row.get("xGChain"), "expected-goals units", "Understat xGChain; historical replay quarantined pending vintage/invariance proof"),
                "xGBuildup": obs("xGBuildup", row.get("xGBuildup"), "expected-goals units", "Understat xGBuildup; historical replay quarantined pending vintage/invariance proof"),
                "penaltiesTaken": missing("penalties_taken", "count", "Not supplied by pinned Understat aggregate source"),
                "penaltiesScored": missing("penalties_scored", "count", "Not supplied by pinned Understat aggregate source"),
            }
            for observation in observations.values():
                if observation["value"] is None:
                    missing_reasons[observation["missingReason"]] += 1
            if observations["nonPenaltyGoals"]["value"] > observations["goals"]["value"]:
                fail(f"NPG > Goals {season}/{player_id}")
            if observations["npxG"]["value"] > observations["xG"]["value"] + 1e-6:
                fail(f"npxG > xG {season}/{player_id}")

            scope = "PLAYER_SEASON_AGGREGATE" if aggregate_multi else "PLAYER_SEASON_CLUB_AGGREGATE"
            records.append({
                "schemaVersion": "nexus-input-v1.1-f1-raw-stint-1.0.0",
                "protocolVersion": "1.1",
                "recordStatus": "QUARANTINED",
                "quarantineReasons": quarantine,
                "technicalKey": {
                    "provider": "UNDERSTAT",
                    "competition": "SERIE_A",
                    "sourceRecordId": record_id,
                    "sourceVersion": source_version,
                },
                "sourceDimensions": {
                    "season": season,
                    "competition": "Serie A",
                    "club": raw_club_label,
                    "sourceUrl": SOURCE_URL,
                    "sourceRepository": SOURCE_REPOSITORY,
                    "sourceCommit": PINNED_COMMIT,
                    "sourceCsvRow": csv_row,
                    "sourceScrapeTimestamp": row.get("scrape_timestamp") or None,
                    "sourceClubLabelsParsed": club_parts,
                },
                "analyticKey": {
                    "playerId": None,
                    "season": season,
                    "league": "Serie A",
                    "club": analytic_club,
                    "stintId": stint_id,
                    "stintOrdinal": stint_ordinal,
                },
                "identity": {
                    "sourcePlayerId": player_id,
                    "mappingStatus": "MAPPING_UNRESOLVED",
                    "sourcePlayerName": row["player_name"],
                },
                "provenance": {
                    "capturedAt": captured_at,
                    "availableAt": None,
                    "sourceHash": source_sha,
                    "sourceRowHash": row_sha,
                    "temporalStatus": "UNKNOWN",
                    "availableAtEvidenceRefs": [],
                },
                "scope": scope,
                "providerRules": "UNDERSTAT_PINNED_PUBLIC_PLAYER_SEASON_SOURCE_V2",
                "providerNpxgXgTolerance": 1e-6,
                "fieldTemporalPolicy": {
                    "observedReplayCandidates": OBSERVED_REPLAY_CANDIDATES,
                    "historicalReplayQuarantinedExpectedMetrics": EXPECTED_REPLAY_QUARANTINED,
                    "releaseCondition": "IMMUTABLE_PRE_CUTOFF_VINTAGE_OR_PROVIDER_INVARIANCE_EVIDENCE",
                },
                "stintEvidence": {
                    "basis": "SINGLE_UNAMBIGUOUS_SOURCE_CLUB_LABEL" if unambiguous_single_club else "SOURCE_STINT_NOT_RESOLVABLE_FROM_PINNED_AGGREGATE",
                    "sourceClubAggregate": raw_club_label,
                    "parsedClubLabels": club_parts,
                    "numericAllocationPerformed": False,
                    "observedSequenceAvailable": False,
                },
                "observations": observations,
            })
            by_season[season] += 1

    if source_multi_club_aggregate_rows == 0:
        fail("grain audit expected multi-club aggregate labels but found none; source-shape assumption unresolved")

    ndjson = "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records).encode("utf-8")
    output_sha = sha256(ndjson)
    (normalized_root / "understat-pinned-source-v2.ndjson").write_bytes(ndjson)
    quarantine_bytes = (json.dumps({
        "schema": "NEXUS_F1_UNDERSTAT_PINNED_MULTI_CLUB_QUARANTINE_V2",
        "protocolVersion": "1.1",
        "status": "EXPLICIT_QUARANTINE",
        "records": raw_multi_club_labels,
    }, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (normalized_root / "multi-club-quarantine-v2.json").write_bytes(quarantine_bytes)

    audit = {
        "schema": "NEXUS_F1_UNDERSTAT_PINNED_SOURCE_AUDIT_V2",
        "protocolVersion": "1.1",
        "status": "PASS_WITH_EXPLICIT_STINT_QUARANTINE",
        "supersedes": {
            "bundleSha256": "7f0c299fbec1e9e952bae98f35262bfa911d337fa0b4192a01d7938bec8410e5",
            "reason": "V1 incorrectly inferred club-split grain from row multiplicity; V2 audits comma-separated multi-club source labels directly.",
        },
        "capturedAt": captured_at,
        "source": {
            "repository": SOURCE_REPOSITORY,
            "commit": PINNED_COMMIT,
            "file": SOURCE_FILE,
            "url": SOURCE_URL,
            "sha256": source_sha,
            "bytes": len(raw),
            "f0SourceFamily": "PLAYER_EVENT_AGGREGATES",
        },
        "coverage": {
            "targetYears": list(TARGET_YEARS),
            "seasons": 11,
            "records": len(records),
            "bySeason": dict(sorted(by_season.items())),
        },
        "grain": {
            "sourceAlreadyClubSplit": False,
            "sourceClubLabelMayAggregateMultipleClubs": True,
            "sourceMultiClubAggregateRows": source_multi_club_aggregate_rows,
            "separateMultiRowPlayerSeasons": separate_multi_row_player_seasons,
            "singleClubRecordsWithDeterministicStintOrdinal1": single_club_records,
            "stintUnresolvedRecords": stint_unresolved_records,
            "numericAllocationPerformed": False,
            "multiClubNumericSplitAttempted": False,
        },
        "integrity": {
            "technicalKeys": len(technical_keys),
            "uniqueSourceRowHashes": len(source_row_hashes),
            "duplicates": 0,
            "missingReasons": dict(sorted(missing_reasons.items())),
            "outputSha256": output_sha,
            "outputBytes": len(ndjson),
            "quarantineSha256": sha256(quarantine_bytes),
        },
        "temporal": {
            "currentCaptureUsedAsHistoricalAvailableAt": False,
            "availableAtAssigned": False,
            "expectedMetricsReplayAdmissible": False,
            "expectedMetricsReleaseCondition": "IMMUTABLE_PRE_CUTOFF_VINTAGE_OR_PROVIDER_INVARIANCE_EVIDENCE",
        },
        "governance": {
            "rawOnly": True,
            "per90Built": False,
            "poolingBuilt": False,
            "shrinkageBuilt": False,
            "imputationPerformed": False,
            "f1Closed": False,
            "f2PlusAuthorized": False,
            "trainingPromotionGranted": False,
            "canonicalMutation": False,
        },
    }
    audit_bytes = (json.dumps(audit, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (OUTPUT_ROOT / "audit.json").write_bytes(audit_bytes)
    (OUTPUT_ROOT / "OUTPUT.sha256").write_text(f"{output_sha}  normalized/understat-pinned-source-v2.ndjson\n", encoding="utf-8")
    print(json.dumps({
        "status": audit["status"],
        "records": len(records),
        "singleClubRecords": single_club_records,
        "multiClubAggregateRows": source_multi_club_aggregate_rows,
        "stintUnresolvedRecords": stint_unresolved_records,
        "sourceSha256": source_sha,
        "outputSha256": output_sha,
    }, indent=2))


if __name__ == "__main__":
    main()
