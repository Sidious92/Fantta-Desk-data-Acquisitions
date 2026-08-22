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
OUTPUT_ROOT = pathlib.Path(os.environ.get("NEXUS_F1_UNDERSTAT_PINNED_OUTPUT", ".nexus-f1-understat-pinned-v1"))
TARGET_YEARS = tuple(range(2014, 2025))
REQUIRED_COLUMNS = {
    "id", "player_name", "team_title", "league", "year", "season", "games", "time",
    "goals", "npg", "assists", "shots", "key_passes", "xG", "npxG", "xA",
    "xGChain", "xGBuildup", "scrape_timestamp"
}
OBSERVED_REPLAY_CANDIDATES = {"games", "time", "goals", "npg", "assists", "shots", "key_passes"}
EXPECTED_REPLAY_QUARANTINED = {"xG", "npxG", "xA", "xGChain", "xGBuildup"}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fail(message: str) -> None:
    raise RuntimeError(f"Nexus F1 Understat pinned acquisition: {message}")


def parse_number(value: str | None, field: str):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise RuntimeError(f"{field}: invalid numeric value {value!r}") from exc
    if number < 0:
        fail(f"{field}: negative value")
    if number.is_integer() and field in {"games", "time", "goals", "npg", "assists", "shots", "key_passes"}:
        return int(number)
    return number


def observation(source_field: str, value: str | None, unit: str, semantics: str):
    parsed = parse_number(value, source_field)
    return {
        "sourceField": source_field,
        "value": parsed,
        "unit": unit,
        "semantics": semantics,
        "transformation": "NONE",
        "missingReason": "UNKNOWN" if parsed is None else None,
    }


def missing(source_field: str, unit: str, semantics: str):
    return {
        "sourceField": source_field,
        "value": None,
        "unit": unit,
        "semantics": semantics,
        "transformation": "NONE",
        "missingReason": "NOT_COLLECTED",
    }


def season_label(year: int) -> str:
    return f"{year}/{str(year + 1)[-2:]}"


def download_source() -> tuple[bytes, str]:
    request = urllib.request.Request(
        SOURCE_URL,
        headers={
            "User-Agent": "FantaNexus-F1-RAW/1.1 (noncommercial research acquisition)",
            "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1",
        },
    )
    captured_at = now_iso()
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 200:
            fail(f"HTTP {response.status} {SOURCE_URL}")
        raw = response.read()
    if not raw:
        fail("downloaded CSV is empty")
    return raw, captured_at


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    raw_root = OUTPUT_ROOT / "raw"
    normalized_root = OUTPUT_ROOT / "normalized"
    raw_root.mkdir(parents=True, exist_ok=True)
    normalized_root.mkdir(parents=True, exist_ok=True)

    raw, captured_at = download_source()
    source_sha256 = sha256_bytes(raw)
    (raw_root / SOURCE_FILE).write_bytes(raw)

    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        fail("CSV header missing")
    missing_columns = sorted(REQUIRED_COLUMNS.difference(reader.fieldnames))
    if missing_columns:
        fail(f"required columns missing: {missing_columns}")

    source_rows = list(reader)
    serie_a_rows = []
    for index, row in enumerate(source_rows, start=2):
        if row.get("league") != "Serie_A":
            continue
        try:
            year = int(row.get("year", ""))
        except ValueError as exc:
            raise RuntimeError(f"CSV row {index}: invalid year") from exc
        if year not in TARGET_YEARS:
            continue
        expected_season = season_label(year)
        if row.get("season") != expected_season:
            fail(f"CSV row {index}: season/year mismatch {row.get('season')} vs {year}")
        if not row.get("id") or not row.get("team_title") or not row.get("player_name"):
            fail(f"CSV row {index}: id/team/player missing")
        serie_a_rows.append((index, year, row))

    if not serie_a_rows:
        fail("no Serie A rows in target years")
    observed_years = sorted({year for _, year, _ in serie_a_rows})
    if observed_years != list(TARGET_YEARS):
        fail(f"target years mismatch: {observed_years}")

    by_player_season: dict[tuple[str, int], list[tuple[int, dict[str, str]]]] = defaultdict(list)
    for index, year, row in serie_a_rows:
        by_player_season[(str(row["id"]), year)].append((index, row))

    records = []
    technical_keys = set()
    source_row_hashes = set()
    multi_club_player_seasons = 0
    multi_club_records = 0
    single_club_records = 0
    missing_reasons = Counter()
    season_counts = Counter()

    source_version = f"PINNED_GIT:{SOURCE_REPOSITORY}@{PINNED_COMMIT}:{SOURCE_FILE}@sha256:{source_sha256}"

    for (player_id, year), rows in sorted(by_player_season.items(), key=lambda item: (item[0][1], item[0][0])):
        clubs = sorted({row["team_title"].strip() for _, row in rows})
        multi_club = len(clubs) > 1
        if multi_club:
            multi_club_player_seasons += 1
        for csv_row_number, row in sorted(rows, key=lambda item: (item[1]["team_title"], item[0])):
            club = row["team_title"].strip()
            season = row["season"]
            row_payload = {key: row.get(key) for key in reader.fieldnames}
            row_sha256 = sha256_bytes(json.dumps(row_payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
            if row_sha256 in source_row_hashes:
                fail(f"duplicate exact source row hash: {row_sha256}")
            source_row_hashes.add(row_sha256)
            club_digest = hashlib.sha256(club.encode("utf-8")).hexdigest()[:16]
            source_record_id = f"pinned-csv:{year}:{player_id}:{club_digest}:row:{csv_row_number}"
            technical_key = ("UNDERSTAT", "SERIE_A", source_record_id, source_version)
            if technical_key in technical_keys:
                fail(f"duplicate technical key {technical_key}")
            technical_keys.add(technical_key)

            quarantine_reasons = ["MAPPING_UNRESOLVED", "TEMPORAL_UNVERIFIED"]
            stint_id = None
            stint_ordinal = None
            if multi_club:
                quarantine_reasons.append("STINT_UNRESOLVED")
                multi_club_records += 1
            else:
                stint_ordinal = 1
                stint_id = f"understat-pinned:{season}:{player_id}:1:{club_digest}"
                single_club_records += 1

            observations = {
                "appearances": observation("games", row.get("games"), "count", "Understat-derived pinned club-row games"),
                "starts": missing("starts", "count", "Not supplied by pinned Understat aggregate source"),
                "substituteAppearances": missing("substitute_appearances", "count", "Not supplied by pinned Understat aggregate source"),
                "minutes": observation("time", row.get("time"), "minutes", "Understat-derived pinned club-row minutes"),
                "goals": observation("goals", row.get("goals"), "count", "Understat goals convention"),
                "nonPenaltyGoals": observation("npg", row.get("npg"), "count", "Understat non-penalty goals convention"),
                "assists": observation("assists", row.get("assists"), "count", "Understat assists convention"),
                "xG": observation("xG", row.get("xG"), "expected-goals units", "Understat expected goals; replay quarantined pending vintage/invariance proof"),
                "npxG": observation("npxG", row.get("npxG"), "expected-goals units", "Understat non-penalty expected goals; replay quarantined pending vintage/invariance proof"),
                "xA": observation("xA", row.get("xA"), "expected-assist units", "Understat expected assists; replay quarantined pending vintage/invariance proof"),
                "shots": observation("shots", row.get("shots"), "count", "Understat shots"),
                "keyPasses": observation("key_passes", row.get("key_passes"), "count", "Understat key passes"),
                "xGChain": observation("xGChain", row.get("xGChain"), "expected-goals units", "Understat xGChain; replay quarantined pending vintage/invariance proof"),
                "xGBuildup": observation("xGBuildup", row.get("xGBuildup"), "expected-goals units", "Understat xGBuildup; replay quarantined pending vintage/invariance proof"),
                "penaltiesTaken": missing("penalties_taken", "count", "Not supplied by pinned Understat aggregate source"),
                "penaltiesScored": missing("penalties_scored", "count", "Not supplied by pinned Understat aggregate source"),
            }
            for obs in observations.values():
                if obs["value"] is None:
                    missing_reasons[obs["missingReason"]] += 1

            goals = observations["goals"]["value"]
            npg = observations["nonPenaltyGoals"]["value"]
            xg = observations["xG"]["value"]
            npxg = observations["npxG"]["value"]
            if goals is not None and npg is not None and npg > goals:
                fail(f"NPG > Goals for {season}/{player_id}/{club}")
            if xg is not None and npxg is not None and npxg > xg + 1e-6:
                fail(f"npxG > xG beyond tolerance for {season}/{player_id}/{club}")

            record = {
                "schemaVersion": "nexus-input-v1.1-f1-raw-stint-1.0.0",
                "protocolVersion": "1.1",
                "recordStatus": "QUARANTINED",
                "quarantineReasons": quarantine_reasons,
                "technicalKey": {
                    "provider": "UNDERSTAT",
                    "competition": "SERIE_A",
                    "sourceRecordId": source_record_id,
                    "sourceVersion": source_version,
                },
                "sourceDimensions": {
                    "season": season,
                    "competition": "Serie A",
                    "club": club,
                    "sourceUrl": SOURCE_URL,
                    "sourceRepository": SOURCE_REPOSITORY,
                    "sourceCommit": PINNED_COMMIT,
                    "sourceCsvRow": csv_row_number,
                    "sourceScrapeTimestamp": row.get("scrape_timestamp") or None,
                },
                "analyticKey": {
                    "playerId": None,
                    "season": season,
                    "league": "Serie A",
                    "club": club,
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
                    "sourceHash": source_sha256,
                    "sourceRowHash": row_sha256,
                    "temporalStatus": "UNKNOWN",
                    "availableAtEvidenceRefs": [],
                },
                "scope": "PLAYER_SEASON_CLUB_AGGREGATE",
                "providerRules": "UNDERSTAT_PINNED_PUBLIC_CLUB_ROW_V1",
                "providerNpxgXgTolerance": 1e-6,
                "fieldTemporalPolicy": {
                    "observedReplayCandidates": sorted(OBSERVED_REPLAY_CANDIDATES),
                    "historicalReplayQuarantinedExpectedMetrics": sorted(EXPECTED_REPLAY_QUARANTINED),
                    "releaseCondition": "IMMUTABLE_PRE_CUTOFF_VINTAGE_OR_PROVIDER_INVARIANCE_EVIDENCE",
                },
                "stintEvidence": {
                    "basis": "SINGLE_SOURCE_CLUB_ROW" if not multi_club else "MULTI_CLUB_SOURCE_ROWS_ORDER_UNKNOWN",
                    "sourceClubCountForPlayerSeason": len(clubs),
                    "sourceClubs": clubs,
                    "observedSequenceRequired": multi_club,
                },
                "observations": observations,
            }
            records.append(record)
            season_counts[season] += 1

    ndjson = "".join(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n" for record in records).encode("utf-8")
    output_path = normalized_root / "understat-pinned-club-segments-v1.ndjson"
    output_path.write_bytes(ndjson)
    output_sha256 = sha256_bytes(ndjson)

    audit = {
        "schema": "NEXUS_F1_UNDERSTAT_PINNED_CLUB_SEGMENTS_AUDIT_V1",
        "protocolVersion": "1.1",
        "status": "PASS",
        "acquisitionKind": "PINNED_PUBLIC_SOURCE_SNAPSHOT_NOT_LIVE_UNDERSTAT_HTML",
        "capturedAt": captured_at,
        "source": {
            "repository": SOURCE_REPOSITORY,
            "commit": PINNED_COMMIT,
            "file": SOURCE_FILE,
            "url": SOURCE_URL,
            "sha256": source_sha256,
            "bytes": len(raw),
            "f0SourceFamily": "PLAYER_EVENT_AGGREGATES",
        },
        "coverage": {
            "targetYears": list(TARGET_YEARS),
            "observedYears": observed_years,
            "seasons": len(observed_years),
            "records": len(records),
            "bySeason": dict(sorted(season_counts.items())),
        },
        "grain": {
            "sourceAlreadyClubSplit": True,
            "numericAllocationPerformed": False,
            "singleClubRecordsWithDeterministicStintOrdinal1": single_club_records,
            "multiClubPlayerSeasons": multi_club_player_seasons,
            "multiClubRecordsStintUnresolved": multi_club_records,
        },
        "integrity": {
            "technicalKeys": len(technical_keys),
            "uniqueSourceRowHashes": len(source_row_hashes),
            "duplicates": 0,
            "missingReasons": dict(sorted(missing_reasons.items())),
            "outputSha256": output_sha256,
            "outputBytes": len(ndjson),
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
    audit_text = (json.dumps(audit, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (OUTPUT_ROOT / "audit.json").write_bytes(audit_text)
    (OUTPUT_ROOT / "OUTPUT.sha256").write_text(f"{output_sha256}  normalized/understat-pinned-club-segments-v1.ndjson\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "records": len(records), "seasons": len(observed_years), "multiClubPlayerSeasons": multi_club_player_seasons, "sourceSha256": source_sha256, "outputSha256": output_sha256}, indent=2))


if __name__ == "__main__":
    main()
