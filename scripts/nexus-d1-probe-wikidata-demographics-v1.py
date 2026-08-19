#!/usr/bin/env python3
"""FantaNexus D1 Wikidata demographics probe.

Probe only. No fuzzy matching, no age derivation, no training promotion.
Persists raw search/entity payloads plus typed mapping/DOB outcomes and SHA-256 manifest.
Transient source failures are recorded per subject and never converted into missing identity evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "FantaNexus-D1-Demographics-Probe/1.1 (+https://github.com/Sidious92/Fantta-Desk-data-Acquisitions)"
HUMAN_QID = "Q5"
ASSOCIATION_FOOTBALL_PLAYER_QID = "Q937857"
REQUEST_SPACING_SECONDS = 0.8


class SourceRequestFailure(RuntimeError):
    def __init__(self, detail: str, attempts: int):
        super().__init__(detail)
        self.detail = detail
        self.attempts = attempts


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.casefold()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")


def request_json(params: dict, attempts: int = 5) -> tuple[dict, bytes]:
    query = urlencode({**params, "format": "json", "formatversion": "2", "maxlag": "5"})
    req = Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last_detail = "unknown error"
    for attempt in range(attempts):
        try:
            with urlopen(req, timeout=35) as response:
                raw = response.read()
                payload = json.loads(raw)
                if isinstance(payload, dict) and payload.get("error"):
                    last_detail = f"MediaWiki API error: {payload['error']}"
                    raise RuntimeError(last_detail)
                time.sleep(REQUEST_SPACING_SECONDS)
                return payload, raw
        except HTTPError as exc:
            last_detail = f"HTTP {exc.code}: {exc.reason}"
        except URLError as exc:
            last_detail = f"URL error: {exc.reason}"
        except Exception as exc:
            last_detail = f"{type(exc).__name__}: {exc}"
        if attempt + 1 < attempts:
            time.sleep(min(12.0, 2.0 * (attempt + 1)))
    raise SourceRequestFailure(last_detail, attempts)


def entity_names(entity: dict) -> set[str]:
    values = set()
    for block_name in ("labels", "aliases"):
        block = entity.get(block_name) or {}
        if block_name == "labels":
            for item in block.values():
                if isinstance(item, dict) and item.get("value"):
                    values.add(norm(item["value"]))
        else:
            for items in block.values():
                for item in items or []:
                    if isinstance(item, dict) and item.get("value"):
                        values.add(norm(item["value"]))
    return {x for x in values if x}


def claim_item_ids(entity: dict, prop: str) -> set[str]:
    out = set()
    for claim in (entity.get("claims") or {}).get(prop, []):
        mainsnak = claim.get("mainsnak") or {}
        dv = mainsnak.get("datavalue") or {}
        value = dv.get("value")
        if isinstance(value, dict) and value.get("id"):
            out.add(value["id"])
    return out


def dob_statements(entity: dict) -> list[dict]:
    out = []
    for claim in (entity.get("claims") or {}).get("P569", []):
        snak = claim.get("mainsnak") or {}
        dv = snak.get("datavalue") or {}
        value = dv.get("value")
        if not isinstance(value, dict) or not value.get("time"):
            continue
        out.append({
            "statementGuid": claim.get("id"),
            "rank": claim.get("rank"),
            "time": value.get("time"),
            "precision": value.get("precision"),
            "calendarmodel": value.get("calendarmodel"),
        })
    return out


def choose_dob(statements: list[dict]) -> tuple[str, dict | None]:
    if not statements:
        return "DOB_MISSING", None
    preferred = [x for x in statements if x.get("rank") == "preferred"]
    candidates = preferred or [x for x in statements if x.get("rank") != "deprecated"]
    distinct = {(x.get("time"), x.get("precision")) for x in candidates}
    if len(distinct) != 1:
        return "DOB_CONFLICT", None
    chosen = sorted(candidates, key=lambda x: x.get("statementGuid") or "")[0]
    return "DOB_VERIFIED", chosen


def fetch_entities_batch(qids: list[str], raw_path: Path) -> dict[str, dict]:
    if not qids:
        return {}
    payload, raw = request_json({
        "action": "wbgetentities",
        "ids": "|".join(qids),
        "props": "info|labels|aliases|descriptions|claims",
        "languages": "en|it|de|fr|es|pt|pl|hr|sr|bs|sq|tr|nl|el",
    })
    raw_path.write_bytes(raw)
    return payload.get("entities") or {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--subjects", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    subjects_doc = json.loads(Path(args.subjects).read_text(encoding="utf-8"))
    subjects = subjects_doc["subjects"]
    out_root = Path(args.output)
    raw_search = out_root / "raw" / "search"
    raw_batches = out_root / "raw" / "entity-batches"
    raw_search.mkdir(parents=True, exist_ok=True)
    raw_batches.mkdir(parents=True, exist_ok=True)

    captured_at = utc_now()
    records = []
    fetched_entities: dict[str, dict] = {}

    for subject in subjects:
        subject_id = subject["subjectId"]
        exact_qids = set()
        search_evidence = []
        request_failures = []

        for lookup in dict.fromkeys(subject["lookupNames"]):
            lookup_slug = slug(lookup)
            try:
                payload, raw = request_json({
                    "action": "wbsearchentities",
                    "search": lookup,
                    "language": "en",
                    "uselang": "en",
                    "type": "item",
                    "limit": 10,
                })
            except SourceRequestFailure as exc:
                request_failures.append({
                    "stage": "SEARCH",
                    "lookup": lookup,
                    "attempts": exc.attempts,
                    "detail": exc.detail,
                })
                continue

            search_path = raw_search / f"{slug(subject_id)}--{lookup_slug}.json"
            search_path.write_bytes(raw)
            hits = payload.get("search") or []
            search_evidence.append({
                "lookup": lookup,
                "path": str(search_path.relative_to(out_root)),
                "sha256": sha256_bytes(raw),
                "returned": len(hits),
            })

            qids = [hit.get("id") for hit in hits if hit.get("id")]
            missing_qids = [qid for qid in qids if qid not in fetched_entities]
            if missing_qids:
                batch_path = raw_batches / f"{slug(subject_id)}--{lookup_slug}.json"
                try:
                    fetched = fetch_entities_batch(missing_qids, batch_path)
                    for qid, ent in fetched.items():
                        fetched_entities[qid] = ent
                except SourceRequestFailure as exc:
                    request_failures.append({
                        "stage": "ENTITY_BATCH",
                        "lookup": lookup,
                        "candidateIds": missing_qids,
                        "attempts": exc.attempts,
                        "detail": exc.detail,
                    })

            lookup_norm = norm(lookup)
            for qid in qids:
                ent = fetched_entities.get(qid)
                if not ent:
                    continue
                if lookup_norm not in entity_names(ent):
                    continue
                if HUMAN_QID not in claim_item_ids(ent, "P31"):
                    continue
                if ASSOCIATION_FOOTBALL_PLAYER_QID not in claim_item_ids(ent, "P106"):
                    continue
                exact_qids.add(qid)

        if len(exact_qids) == 1:
            qid = next(iter(exact_qids))
            ent = fetched_entities[qid]
            statements = dob_statements(ent)
            dob_state, dob = choose_dob(statements)
            record = {
                **subject,
                "probeStatus": "EVALUATED" if not request_failures else "EVALUATED_WITH_REQUEST_FAILURES",
                "mappingStatus": "IDENTITY_VERIFIED",
                "mappingMethod": "EXACT_LABEL_OR_ALIAS_UNIQUE_HUMAN_FOOTBALLER",
                "wikidataItemId": qid,
                "wikidataLastRevisionId": ent.get("lastrevid"),
                "wikidataModified": ent.get("modified"),
                "dateOfBirthStatus": dob_state,
                "dateOfBirth": dob,
                "allDobStatements": statements,
                "historicalAdmissibility": "NOT_ESTABLISHED_CURRENT_PROBE",
                "searchEvidence": search_evidence,
                "requestFailures": request_failures,
            }
        elif len(exact_qids) > 1:
            record = {
                **subject,
                "probeStatus": "EVALUATED" if not request_failures else "EVALUATED_WITH_REQUEST_FAILURES",
                "mappingStatus": "IDENTITY_AMBIGUOUS",
                "mappingMethod": None,
                "wikidataCandidateIds": sorted(exact_qids),
                "dateOfBirthStatus": "IDENTITY_UNRESOLVED",
                "dateOfBirth": None,
                "historicalAdmissibility": "NOT_ESTABLISHED_CURRENT_PROBE",
                "missingReason": "MAPPING_UNRESOLVED",
                "searchEvidence": search_evidence,
                "requestFailures": request_failures,
            }
        elif request_failures:
            record = {
                **subject,
                "probeStatus": "NOT_FULLY_EVALUATED_REQUEST_FAILURE",
                "mappingStatus": None,
                "mappingMethod": None,
                "wikidataCandidateIds": [],
                "dateOfBirthStatus": "NOT_EVALUATED_TECHNICAL",
                "dateOfBirth": None,
                "historicalAdmissibility": "NOT_ESTABLISHED_CURRENT_PROBE",
                "missingReason": "UNKNOWN",
                "searchEvidence": search_evidence,
                "requestFailures": request_failures,
            }
        else:
            record = {
                **subject,
                "probeStatus": "EVALUATED",
                "mappingStatus": "IDENTITY_UNRESOLVED",
                "mappingMethod": None,
                "wikidataCandidateIds": [],
                "dateOfBirthStatus": "IDENTITY_UNRESOLVED",
                "dateOfBirth": None,
                "historicalAdmissibility": "NOT_ESTABLISHED_CURRENT_PROBE",
                "missingReason": "MAPPING_UNRESOLVED",
                "searchEvidence": search_evidence,
                "requestFailures": [],
            }
        records.append(record)

    mapping_counts = {}
    probe_counts = {}
    dob_counts = {}
    request_failure_count = 0
    for record in records:
        mapping_key = record.get("mappingStatus") or "NOT_EVALUATED_TECHNICAL"
        mapping_counts[mapping_key] = mapping_counts.get(mapping_key, 0) + 1
        probe_key = record["probeStatus"]
        probe_counts[probe_key] = probe_counts.get(probe_key, 0) + 1
        dob_key = record["dateOfBirthStatus"]
        dob_counts[dob_key] = dob_counts.get(dob_key, 0) + 1
        request_failure_count += len(record.get("requestFailures") or [])

    collision = [r for r in records if r["subjectId"].startswith("historical-fc-65-")]
    collision_qids = [r.get("wikidataItemId") for r in collision if r.get("mappingStatus") == "IDENTITY_VERIFIED"]
    collision_pass = len(collision_qids) == 2 and len(set(collision_qids)) == 2

    scientific_pass = (
        collision_pass
        and mapping_counts.get("IDENTITY_AMBIGUOUS", 0) == 0
        and mapping_counts.get("NOT_EVALUATED_TECHNICAL", 0) == 0
        and request_failure_count == 0
    )

    result = {
        "schema": "NEXUS_D1_WIKIDATA_DEMOGRAPHICS_PROBE_RESULT_V1",
        "probeImplementationVersion": "1.1",
        "protocolVersion": "1.1",
        "status": "PASS" if scientific_pass else "REVIEW_REQUIRED",
        "declaredUse": "CURRENT_PROBE",
        "capturedAt": captured_at,
        "source": {
            "provider": "Wikidata",
            "api": API,
            "license": "CC0 structured data",
            "queryMethods": ["wbsearchentities", "wbgetentities batch"],
        },
        "rules": {
            "fuzzyMatchingUsed": False,
            "computedAgeDerived": False,
            "currentRetrievalImpliesHistoricalAsOf": False,
            "trainingPromotionGranted": False,
            "exactMapping": "normalized exact label/alias + human Q5 + association football player Q937857; exactly one entity",
            "requestFailureCanBecomeMissingIdentity": False,
        },
        "summary": {
            "subjects": len(records),
            "probeStatus": probe_counts,
            "mappingStatus": mapping_counts,
            "dobStatus": dob_counts,
            "sourceRequestFailureCount": request_failure_count,
            "knownProviderIdReuseRegressionPass": collision_pass,
        },
        "records": records,
    }
    (out_root / "RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest_files = []
    for path in sorted(p for p in out_root.rglob("*") if p.is_file() and p.name != "MANIFEST.json"):
        data = path.read_bytes()
        manifest_files.append({
            "path": str(path.relative_to(out_root)),
            "size": len(data),
            "sha256": sha256_bytes(data),
        })
    manifest = {
        "schema": "NEXUS_D1_WIKIDATA_DEMOGRAPHICS_PROBE_MANIFEST_V1",
        "generatedAt": utc_now(),
        "files": manifest_files,
        "fileCount": len(manifest_files),
        "canonicalContentSha256": hashlib.sha256(
            "\n".join(f"{x['path']}\t{x['size']}\t{x['sha256']}" for x in manifest_files).encode("utf-8")
        ).hexdigest(),
    }
    (out_root / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(result["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
