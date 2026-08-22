#!/usr/bin/env python3
"""Build compact D1 second-pass identity/DOB surface from persisted first-pass results.

No name-only/fuzzy cross-scope deduplication is allowed. Cross-scope overlap is
recognized only when both records already carry the same verified Wikidata item.
No performance statistics are transferred.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load(path: Path):
    b = path.read_bytes()
    return json.loads(b), {"path": str(path), "size": len(b), "sha256": sha256_bytes(b)}


def status(r: dict, *keys):
    for k in keys:
        if r.get(k) is not None:
            return r.get(k)
    return None


ALLOWED = {
    "subjectId", "bridgePersonKey", "understatPlayerId",
    "fantacalcioPlayerId", "fantacalcioId", "playerId",
    "sourcePlayerId", "sourceIdentityId",
    "canonicalName", "sourceName", "name", "lookupName", "lookupNames",
    "club", "sourceClub", "contextClubs", "seasons",
    "mappingStatus", "mappingMethod", "matchMethod",
    "dateOfBirthStatus", "dobStatus", "dateOfBirth",
    "wikidataItemId", "wikidataLastRevisionId", "wikidataModified",
    "exactCandidateIds", "contextEvidence", "allDobStatements",
    "missingReason", "historicalAdmissibility",
    "sourceBridge", "identityBridge", "sourceIdentity", "sourceContext",
}

BANNED_TOKENS = (
    "goal", "assist", "xg", "xa", "shot", "minute", "rating", "vote",
    "quotation", "fvm", "fantasy", "prediction", "target", "feature"
)


def compact_record(scope: str, r: dict) -> dict:
    out = {"scope": scope}
    for k in ALLOWED:
        if k in r:
            out[k] = r[k]
    # Normalize status fields while preserving originals when present.
    out["mappingStatus"] = status(r, "mappingStatus", "identityStatus")
    out["dateOfBirthStatus"] = status(r, "dateOfBirthStatus", "dobStatus")
    # Stable source-record locator into the persisted first-pass result.
    sid = r.get("subjectId") or r.get("fantacalcioPlayerId") or r.get("playerId") or r.get("understatPlayerId")
    out["firstPassSubjectLocator"] = str(sid) if sid is not None else None
    return out


def assert_identity_only(obj):
    def walk(v, path=""):
        if isinstance(v, dict):
            for k, x in v.items():
                lk = k.lower()
                if any(tok in lk for tok in BANNED_TOKENS):
                    raise RuntimeError(f"PERFORMANCE_FIELD_FORBIDDEN:{path}/{k}")
                walk(x, f"{path}/{k}")
        elif isinstance(v, list):
            for i, x in enumerate(v):
                walk(x, f"{path}/{i}")
    walk(obj)


def is_open(r: dict) -> bool:
    mapping = status(r, "mappingStatus", "identityStatus")
    dob = status(r, "dateOfBirthStatus", "dobStatus")
    return mapping != "IDENTITY_VERIFIED" or dob != "DOB_VERIFIED"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", required=True)
    ap.add_argument("--historical", required=True)
    ap.add_argument("--historical-surface-manifest", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    current, current_meta = load(Path(args.current))
    historical, historical_meta = load(Path(args.historical))
    hsurf, hsurf_meta = load(Path(args.historical_surface_manifest))

    cr = current.get("records") or []
    hr = historical.get("records") or []
    if len(cr) != 505:
        raise RuntimeError(f"EXPECTED_CURRENT_505_GOT_{len(cr)}")
    if len(hr) != 2048:
        raise RuntimeError(f"EXPECTED_HISTORICAL_2048_GOT_{len(hr)}")
    if (current.get("summary") or {}).get("requestFailures") != 0:
        raise RuntimeError("CURRENT_FIRST_PASS_HAS_REQUEST_FAILURES")
    if (historical.get("summary") or {}).get("requestFailures") != 0:
        raise RuntimeError("HISTORICAL_FIRST_PASS_HAS_REQUEST_FAILURES")
    if hsurf.get("source", {}).get("fantacalcioIdsNeverResolvedToUnderstat") != 445:
        raise RuntimeError("EXPECTED_EXPLICIT_HISTORICAL_UNRESOLVED_ID_GAP_445")

    co = [compact_record("CURRENT_2026_27", r) for r in cr if is_open(r)]
    ho = [compact_record("HISTORICAL_RESOLVED_PERSON_2015_16_2025_26", r) for r in hr if is_open(r)]
    if len(co) != 127:
        raise RuntimeError(f"EXPECTED_CURRENT_OPEN_127_GOT_{len(co)}")
    if len(ho) != 155:
        raise RuntimeError(f"EXPECTED_HISTORICAL_OPEN_155_GOT_{len(ho)}")

    assert_identity_only(co)
    assert_identity_only(ho)

    # Deterministic overlap only: same already-verified Wikidata item on both scopes.
    by_qid = defaultdict(list)
    for r in co + ho:
        qid = r.get("wikidataItemId")
        if qid and r.get("mappingStatus") == "IDENTITY_VERIFIED":
            by_qid[qid].append({"scope": r["scope"], "firstPassSubjectLocator": r.get("firstPassSubjectLocator")})
    overlap = []
    for qid, refs in sorted(by_qid.items()):
        scopes = {x["scope"] for x in refs}
        if len(scopes) > 1:
            overlap.append({"wikidataItemId": qid, "records": refs, "method": "SAME_ALREADY_VERIFIED_WIKIDATA_ITEM"})

    def counts(xs):
        return {
            "mappingStatus": dict(sorted(Counter(x.get("mappingStatus") or "NULL" for x in xs).items())),
            "dateOfBirthStatus": dict(sorted(Counter(x.get("dateOfBirthStatus") or "NULL" for x in xs).items())),
        }

    captured = now()
    result = {
        "schema": "NEXUS_D1_SECOND_PASS_SUBJECT_SURFACE_V1",
        "protocolVersion": "1.1",
        "status": "PASS",
        "capturedAt": captured,
        "scope": {
            "currentFirstPassSubjects": 505,
            "historicalResolvedPersonFirstPassSubjects": 2048,
            "currentOpenRecords": len(co),
            "historicalOpenRecords": len(ho),
            "rawOpenRecordsBeforeCrossScopeOverlap": len(co) + len(ho),
            "historicalFantacalcioIdsNeverResolvedToUnderstat": 445,
            "historicalUnresolved445Disposition": "SEPARATE_D1_SECOND_PASS_SUBLOT_REQUIRED_FROM_D0_AUTHORITY"
        },
        "counts": {"current": counts(co), "historical": counts(ho)},
        "crossScopeDeterministicOverlap": {
            "count": len(overlap),
            "groups": overlap,
            "nameOnlyDeduplicationUsed": False,
            "fuzzyDeduplicationUsed": False
        },
        "governance": {
            "performanceStatisticsTransferred": False,
            "targetValuesTransferred": False,
            "computedAgeDerived": False,
            "dobInferred": False,
            "fuzzyMatchingUsed": False,
            "nameOnlyCrossScopeMergeUsed": False,
            "trainingPromotionGranted": False,
            "f1Started": False,
            "d2Started": False
        },
        "firstPassAuthority": {
            "current": current_meta,
            "historical": historical_meta,
            "historicalSubjectSurface": hsurf_meta
        },
        "currentOpen": co,
        "historicalOpen": ho
    }

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    rb = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode()
    (out / "SECOND_PASS_SUBJECTS.json").write_bytes(rb)
    manifest = {
        "schema": "NEXUS_D1_SECOND_PASS_SUBJECT_SURFACE_MANIFEST_V1",
        "generatedAt": captured,
        "status": "PASS",
        "output": {
            "path": "SECOND_PASS_SUBJECTS.json",
            "size": len(rb),
            "sha256": sha256_bytes(rb)
        },
        "expectedCounts": {
            "currentOpen": 127,
            "historicalOpen": 155,
            "rawOpenBeforeOverlap": 282,
            "historicalUnresolvedIdGap": 445
        },
        "governance": result["governance"]
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({
        "status": "PASS",
        "currentOpen": len(co),
        "historicalOpen": len(ho),
        "rawOpen": len(co) + len(ho),
        "deterministicCrossScopeOverlapGroups": len(overlap),
        "historicalUnresolvedIdGap": 445
    }, indent=2))


if __name__ == "__main__":
    main()
