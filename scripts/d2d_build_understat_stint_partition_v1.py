#!/usr/bin/env python3
import csv
import hashlib
import io
import json
import urllib.request
from collections import Counter
from pathlib import Path

UNDERSTAT_COMMIT = "768b7ca0b977a5e6b4b429c7b0cf750e8269f2fc"
UNDERSTAT_BLOB_SHA1 = "ddf4327251bb781f88b6edc4662bf20e5379ff3f"
UNDERSTAT_SHA256 = "b78fad5f01844a0fdab0d89474dafba9b86c586d2f0ce88f0ce2c9af70d2bc64"
UNDERSTAT_URL = f"https://raw.githubusercontent.com/vibedatascience/understat_players_aggregated/{UNDERSTAT_COMMIT}/understat_players_aggregated_2014_2024.csv"
D1_COMMIT = "d0cab101cc90f65ee0b1982e7ca974cd95c5d3b9"
D1_SHA256 = "952bdf1d4cfb81a0683bff1f78d949b6350b11be1cc27d20059f7ace651bb53c"
D1_URL = f"https://raw.githubusercontent.com/Sidious92/Fantta-Desk-data-Acquisitions/{D1_COMMIT}/data/nexus-d1/final-v3/IDENTITY_MASTER.json"
OUT = Path("data/nexus-d2/final-v1/understat")
SHARD_SIZE = 1000


def fetch(url):
    with urllib.request.urlopen(url, timeout=90) as r:
        return r.read()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def stable_hash(prefix, *parts):
    payload = "\x1f".join("" if p is None else str(p) for p in parts).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(payload).hexdigest()[:32]}"


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return {"path": str(path), "bytes": len(raw), "sha256": sha256_bytes(raw)}


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    raw = path.read_bytes()
    return {"path": str(path), "bytes": len(raw), "sha256": sha256_bytes(raw), "rows": len(rows)}


understat_raw = fetch(UNDERSTAT_URL)
observed_blob = hashlib.sha1(b"blob " + str(len(understat_raw)).encode("ascii") + b"\0" + understat_raw).hexdigest()
if observed_blob != UNDERSTAT_BLOB_SHA1:
    raise SystemExit(f"Understat git blob mismatch: {observed_blob}")
if sha256_bytes(understat_raw) != UNDERSTAT_SHA256:
    raise SystemExit("Understat SHA256 mismatch")

d1_raw = fetch(D1_URL)
if sha256_bytes(d1_raw) != D1_SHA256:
    raise SystemExit("D1 SHA256 mismatch")
d1 = json.loads(d1_raw)
understat_to_person = {}
for p in d1.get("persons", []):
    if not p.get("globalPersonPromotionGranted"):
        continue
    for a in p.get("providerAliases", []):
        if a.get("provider") == "Understat" and a.get("providerId") is not None:
            key = str(a["providerId"])
            if key in understat_to_person and understat_to_person[key] != p["personKey"]:
                raise SystemExit(f"D1 duplicate Understat alias {key}")
            understat_to_person[key] = p["personKey"]

reader = csv.DictReader(io.StringIO(understat_raw.decode("utf-8-sig")))
required = {"id", "player_name", "team_title", "league", "season", "scrape_timestamp"}
if not required.issubset(set(reader.fieldnames or [])):
    raise SystemExit(f"Missing columns: {required - set(reader.fieldnames or [])}")

candidate = []
residual = []
source_bound_rows = 0
for line_no, r in enumerate(reader, start=2):
    source_id = str(r.get("id") or "")
    person_key = understat_to_person.get(source_id)
    if not person_key:
        continue
    source_bound_rows += 1
    team = (r.get("team_title") or "").strip()
    league = (r.get("league") or "").strip()
    season = (r.get("season") or "").strip()
    locator = f"understat_players_aggregated_2014_2024.csv#line={line_no}"
    row_fingerprint = hashlib.sha256(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    base = {
        "identityKey": person_key,
        "identityAuthorityRef": f"D1_IDENTITY_MASTER@{D1_COMMIT}:{D1_SHA256}",
        "source": "UNDERSTAT_PINNED_MULTI_LEAGUE",
        "sourcePlayerId": source_id,
        "season": season,
        "competition": league,
        "leagueOrCompetitionId": None,
        "capturedAt": r.get("scrape_timestamp") or None,
        "availableAt": None,
        "availableAtMissingReason": "UNKNOWN",
        "sourceRecordLocator": locator,
        "sourceRecordSha256": row_fingerprint,
        "sourceVersion": UNDERSTAT_COMMIT,
        "sourceHashSha256": UNDERSTAT_SHA256,
        "mappingStatus": "EXACT_D1_UNDERSTAT_PROVIDER_ID",
        "conflictStatus": "NONE_OBSERVED"
    }
    if "," in team:
        residual.append({
            **base,
            "observedClubField": team,
            "missingReason": "AGGREGATED_MULTI_CLUB_ROW",
            "canonicalStintConstructed": False,
            "resolutionPolicy": "PRESERVE_RAW_AGGREGATE_NO_STRING_SPLIT_NO_METRIC_ALLOCATION"
        })
        continue
    stint_key = stable_hash("nexus-stint-v1", person_key, "UNDERSTAT_PINNED_MULTI_LEAGUE", season, league, team, "occurrence-0")
    candidate.append({
        **base,
        "club": team,
        "sourceClubId": None,
        "stintKey": stint_key,
        "occurrenceDiscriminator": "SOURCE_SINGLE_CLUB_SEASON_ROW",
        "stintStart": None,
        "stintEnd": None,
        "stintBoundaryMissingReason": "STINT_BOUNDARY_NOT_OBSERVED",
        "missingReason": None,
        "canonicalStintConstructed": True
    })

candidate.sort(key=lambda x: (x["identityKey"], x["season"], x["competition"], x["club"], x["sourcePlayerId"]))
residual.sort(key=lambda x: (x["identityKey"], x["season"], x["competition"], x["observedClubField"], x["sourcePlayerId"]))

stint_keys = [r["stintKey"] for r in candidate]
if len(stint_keys) != len(set(stint_keys)):
    raise SystemExit("Duplicate canonical stintKey")

source_tuple_counts = Counter((r["identityKey"], r["season"], r["competition"], r["club"]) for r in candidate)
if any(v != 1 for v in source_tuple_counts.values()):
    raise SystemExit("Duplicate canonical analytical tuple")

OUT.mkdir(parents=True, exist_ok=True)
files = []
for i in range(0, len(candidate), SHARD_SIZE):
    shard = candidate[i:i+SHARD_SIZE]
    files.append(write_jsonl(OUT / f"stints-{i//SHARD_SIZE:03d}.jsonl", shard))
files.append(write_jsonl(OUT / "residuals.jsonl", residual))

counts_by_league = Counter(r["competition"] for r in candidate)
residuals_by_league = Counter(r["competition"] for r in residual)
counts_by_season = Counter(r["season"] for r in candidate)
residuals_by_season = Counter(r["season"] for r in residual)
registry = {
    "schema": "NEXUS_D2D_UNDERSTAT_STINT_PARTITION_V1",
    "status": "FROZEN_PARTITION_PASS",
    "canonicalAnalyticalGrain": "player-season-league-club-stint",
    "sourceAuthorities": {
        "understat": {"repository": "vibedatascience/understat_players_aggregated", "commit": UNDERSTAT_COMMIT, "gitBlobSha1": UNDERSTAT_BLOB_SHA1, "sha256": UNDERSTAT_SHA256},
        "d1Identity": {"repository": "Sidious92/Fantta-Desk-data-Acquisitions", "commit": D1_COMMIT, "path": "data/nexus-d1/final-v3/IDENTITY_MASTER.json", "sha256": D1_SHA256}
    },
    "counts": {
        "d1UnderstatAliases": len(understat_to_person),
        "d1BoundSourceRows": source_bound_rows,
        "canonicalSingleClubStintRows": len(candidate),
        "aggregatedMultiClubResidualRows": len(residual),
        "uniqueCanonicalPersons": len({r["identityKey"] for r in candidate}),
        "uniqueResidualPersons": len({r["identityKey"] for r in residual}),
        "residualShareOfD1BoundRows": len(residual) / source_bound_rows if source_bound_rows else None
    },
    "canonicalRowsByLeague": dict(sorted(counts_by_league.items())),
    "residualRowsByLeague": dict(sorted(residuals_by_league.items())),
    "canonicalRowsBySeason": dict(sorted(counts_by_season.items())),
    "residualRowsBySeason": dict(sorted(residuals_by_season.items())),
    "validation": {
        "sourceHashesVerified": True,
        "exactD1ProviderBindingOnly": True,
        "duplicateStintKeys": 0,
        "duplicateAnalyticalTuples": 0,
        "commaSeparatedClubRowsPromoted": 0,
        "metricAllocationPerformed": False,
        "fuzzyMatchingUsed": False,
        "rawSourceMutated": False
    },
    "files": files,
    "governance": {
        "partitionOnly": True,
        "fullD2Complete": False,
        "canonicalPredictiveEngineModified": False,
        "f1Started": False
    }
}
reg_meta = write_json(OUT / "REGISTRY.json", registry)
manifest = {
    "schema": "NEXUS_D2D_UNDERSTAT_PARTITION_MANIFEST_V1",
    "status": "PASS",
    "registry": reg_meta,
    "contentFiles": files,
    "treeContentDigestSha256": hashlib.sha256("\n".join(f"{x['path']}\t{x['sha256']}\t{x['bytes']}" for x in sorted(files, key=lambda y:y['path'])).encode("utf-8")).hexdigest()
}
write_json(OUT / "MANIFEST.json", manifest)
print(json.dumps(registry["counts"], indent=2))
print(f"Wrote {OUT}")
