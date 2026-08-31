from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

OUT = Path(
    os.environ.get(
        "NEXUS_HIST_RESIDUAL10_OUT",
        ".nexus-historical-residual-10-wayback",
    )
)
TIMEOUT = float(os.environ.get("NEXUS_REQUEST_TIMEOUT_SECONDS", "60"))
USER_AGENT = "FantaNexus-Historical-Residual10-Wayback-Recovery/1.0"
MAX_CDX_ROWS = int(os.environ.get("NEXUS_CDX_MAX_ROWS", "2000"))
MAX_FETCHES_PER_SOURCE = int(os.environ.get("NEXUS_MAX_FETCHES_PER_SOURCE", "12"))
SLEEP_SECONDS = float(os.environ.get("NEXUS_REQUEST_SLEEP_SECONDS", "0.35"))

CDX_FIELDS = [
    "timestamp",
    "original",
    "statuscode",
    "mimetype",
    "digest",
    "length",
]

TRANSFER_TERMS = (
    "acquis",
    "trasfer",
    "tesser",
    "prestito",
    "temporane",
    "definitiv",
    "svincol",
    "riscatt",
    "provenient",
    "accordo",
    "contract",
    "sign",
    "loan",
    "transfer",
)

TARGETS = [
    {
        "candidate": "Bruno Alves",
        "target_club": "PAR",
        "window_from": "20180709",
        "window_to": "20180716",
        "sources": [
            {
                "authority": "PARMA_CALCIO_1913",
                "role": "destination_club",
                "hosts": ["parmacalcio1913.com", "www.parmacalcio1913.com"],
                "url_token": "alves",
            }
        ],
    },
    {
        "candidate": "Lorenzo Dickmann",
        "target_club": "SPA",
        "window_from": "20180625",
        "window_to": "20180702",
        "sources": [
            {
                "authority": "SPAL",
                "role": "destination_club",
                "hosts": ["spalferrara.it", "www.spalferrara.it"],
                "url_token": "dickmann",
            }
        ],
    },
    {
        "candidate": "Johan Djourou",
        "target_club": "SPA",
        "window_from": "20180717",
        "window_to": "20180726",
        "sources": [
            {
                "authority": "SPAL",
                "role": "destination_club",
                "hosts": ["spalferrara.it", "www.spalferrara.it"],
                "url_token": "djourou",
            },
            {
                "authority": "ANTALYASPOR",
                "role": "prior_club",
                "hosts": ["antalyaspor.com.tr", "www.antalyaspor.com.tr"],
                "url_token": "djourou",
            },
        ],
    },
    {
        "candidate": "Koray Gunter",
        "target_club": "GEN",
        "window_from": "20180721",
        "window_to": "20180730",
        "sources": [
            {
                "authority": "GENOA_CFC",
                "role": "destination_club",
                "hosts": ["genoacfc.it", "www.genoacfc.it"],
                "url_token": "gunter",
            },
            {
                "authority": "GALATASARAY",
                "role": "prior_club",
                "hosts": ["galatasaray.org", "www.galatasaray.org"],
                "url_token": "gunter",
            },
        ],
    },
    {
        "candidate": "Alban Lafont",
        "target_club": "FIO",
        "window_from": "20180628",
        "window_to": "20180706",
        "sources": [
            {
                "authority": "ACF_FIORENTINA_VIOLACHANNEL",
                "role": "destination_club",
                "hosts": ["violachannel.tv", "www.violachannel.tv", "it.violachannel.tv"],
                "url_token": "lafont",
            },
            {
                "authority": "TOULOUSE_FC",
                "role": "prior_club",
                "hosts": ["toulousefc.com", "www.toulousefc.com"],
                "url_token": "lafont",
            },
        ],
    },
    {
        "candidate": "Sebastiano Luperto",
        "target_club": "NAP",
        "window_from": "20180601",
        "window_to": "20180820",
        "sources": [
            {
                "authority": "SSC_NAPOLI",
                "role": "destination_club",
                "hosts": ["sscnapoli.it", "www.sscnapoli.it"],
                "url_token": "luperto",
            },
            {
                "authority": "EMPOLI_FC",
                "role": "prior_club",
                "hosts": [
                    "empolicalcio.net",
                    "www.empolicalcio.net",
                    "empolifc.com",
                    "www.empolifc.com",
                ],
                "url_token": "luperto",
            },
        ],
    },
    {
        "candidate": "Jacob Rasmussen",
        "target_club": "EMP",
        "window_from": "20180702",
        "window_to": "20180709",
        "sources": [
            {
                "authority": "EMPOLI_FC",
                "role": "destination_club",
                "hosts": [
                    "empolicalcio.net",
                    "www.empolicalcio.net",
                    "empolifc.com",
                    "www.empolifc.com",
                ],
                "url_token": "rasmussen",
            },
            {
                "authority": "ROSENBORG_BK",
                "role": "prior_club",
                "hosts": ["rbk.no", "www.rbk.no"],
                "url_token": "rasmussen",
            },
        ],
    },
    {
        "candidate": "Mattia Sprocati",
        "target_club": "LAZ",
        "window_from": "20180626",
        "window_to": "20180703",
        "sources": [
            {
                "authority": "SS_LAZIO",
                "role": "destination_club",
                "hosts": ["sslazio.it", "www.sslazio.it"],
                "url_token": "sprocati",
            },
            {
                "authority": "US_SALERNITANA_1919",
                "role": "prior_club",
                "hosts": ["ussalernitana1919.it", "www.ussalernitana1919.it"],
                "url_token": "sprocati",
            },
        ],
    },
    {
        "candidate": "Strahinja Tanasijevic",
        "target_club": "CHI",
        "window_from": "20180128",
        "window_to": "20180715",
        "sources": [
            {
                "authority": "CHIEVOVERONA",
                "role": "destination_club",
                "hosts": ["chievoverona.it", "www.chievoverona.it"],
                "url_token": "tanasijevic",
            },
            {
                "authority": "FK_RAD",
                "role": "prior_club",
                "hosts": ["fkrad.rs", "www.fkrad.rs"],
                "url_token": "tanasijevic",
            },
        ],
        "scope_note": (
            "Window deliberately includes the 2018-01-31 loan announcement so the "
            "archive can distinguish prior-season loan evidence from any later "
            "2018/19 redemption evidence. No season inference is made here."
        ),
    },
    {
        "candidate": "Luca Valzania",
        "target_club": "ATA",
        "window_from": "20180620",
        "window_to": "20180710",
        "sources": [
            {
                "authority": "ATALANTA_BC",
                "role": "destination_club",
                "hosts": ["atalanta.it", "www.atalanta.it"],
                "url_token": "valzania",
            },
            {
                "authority": "DELFINO_PESCARA_1936",
                "role": "prior_club",
                "hosts": ["pescaracalcio.com", "www.pescaracalcio.com"],
                "url_token": "valzania",
            },
        ],
    },
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def candidate_tokens(name: str) -> list[str]:
    return [token for token in normalize(name).split() if len(token) >= 3]


def has_candidate_identity(text: str, name: str) -> bool:
    blob = normalize(text)
    tokens = candidate_tokens(name)
    return bool(tokens) and all(token in blob for token in tokens)


def bounded_snippet(text: str, name: str, radius: int = 900) -> str:
    compact = " ".join(text.split())
    lower = normalize(compact)
    positions = [
        lower.find(token)
        for token in candidate_tokens(name)
        if lower.find(token) >= 0
    ]
    if not positions:
        return compact[: 2 * radius]
    pos = min(positions)
    # Normalization changes offsets slightly; this is diagnostic text only.
    start = max(0, pos - radius)
    end = min(len(compact), pos + radius)
    return compact[start:end]


def transfer_term_hits(text: str) -> list[str]:
    blob = normalize(text)
    hits = []
    for term in TRANSFER_TERMS:
        needle = normalize(term)
        if needle and needle in blob:
            hits.append(term)
    return sorted(set(hits))


def parse_cdx(payload: object) -> list[dict]:
    if not isinstance(payload, list) or not payload:
        return []
    header = payload[0]
    if header != CDX_FIELDS:
        raise RuntimeError(f"unexpected CDX header: {header!r}")
    return [
        dict(zip(header, row))
        for row in payload[1:]
        if isinstance(row, list) and len(row) == len(header)
    ]


def cdx_request(
    session: requests.Session,
    host: str,
    url_token: str,
    date_from: str,
    date_to: str,
    use_original_filter: bool,
) -> tuple[str, list[dict]]:
    params: list[tuple[str, str]] = [
        ("url", f"{host}/*"),
        ("output", "json"),
        ("fl", ",".join(CDX_FIELDS)),
        ("filter", "statuscode:200"),
        ("from", date_from),
        ("to", date_to),
        ("collapse", "urlkey"),
        ("limit", str(MAX_CDX_ROWS)),
    ]
    if use_original_filter:
        params.append(("filter", f"original:.*{re.escape(url_token)}.*"))
    query_url = "https://web.archive.org/cdx/search/cdx?" + urlencode(params)
    response = session.get(query_url, timeout=TIMEOUT)
    response.raise_for_status()
    rows = parse_cdx(response.json())
    if not use_original_filter:
        token = normalize(url_token)
        rows = [
            row
            for row in rows
            if token in normalize(str(row.get("original") or ""))
        ]
    return query_url, rows


def discover_rows(
    session: requests.Session,
    host: str,
    url_token: str,
    date_from: str,
    date_to: str,
) -> tuple[list[dict], list[dict]]:
    query_records = []
    try:
        query_url, rows = cdx_request(
            session,
            host,
            url_token,
            date_from,
            date_to,
            use_original_filter=True,
        )
        query_records.append(
            {
                "host": host,
                "mode": "CDX_ORIGINAL_REGEX_FILTER",
                "query_url": query_url,
                "status": "PASS",
                "row_count": len(rows),
            }
        )
        if rows:
            return rows, query_records
    except Exception as exc:
        query_records.append(
            {
                "host": host,
                "mode": "CDX_ORIGINAL_REGEX_FILTER",
                "status": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )

    # Fallback is intentionally bounded by date and MAX_CDX_ROWS, then filtered
    # locally by URL token. This avoids silently treating arbitrary club pages
    # as candidate evidence.
    try:
        query_url, rows = cdx_request(
            session,
            host,
            url_token,
            date_from,
            date_to,
            use_original_filter=False,
        )
        query_records.append(
            {
                "host": host,
                "mode": "CDX_BOUNDED_HOST_SCAN_LOCAL_URL_FILTER",
                "query_url": query_url,
                "status": "PASS",
                "row_count": len(rows),
            }
        )
        return rows, query_records
    except Exception as exc:
        query_records.append(
            {
                "host": host,
                "mode": "CDX_BOUNDED_HOST_SCAN_LOCAL_URL_FILTER",
                "status": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return [], query_records


def raw_snapshot_url(row: dict) -> str:
    return f"https://web.archive.org/web/{row['timestamp']}id_/{row['original']}"


def safe_filename(candidate: str, authority: str, timestamp: str, digest: str) -> str:
    left = re.sub(r"[^a-z0-9]+", "-", normalize(candidate)).strip("-")
    right = re.sub(r"[^a-z0-9]+", "-", normalize(authority)).strip("-")
    dig = re.sub(r"[^A-Za-z0-9]+", "", digest or "")[:16] or "nodigest"
    return f"{left}__{right}__{timestamp}__{dig}.html"


def fetch_candidate(
    session: requests.Session,
    row: dict,
    candidate: str,
    authority: str,
    role: str,
) -> tuple[dict, bytes | None]:
    url = raw_snapshot_url(row)
    result = {
        "authority": authority,
        "source_role": role,
        "capture_timestamp": row.get("timestamp"),
        "original_url": row.get("original"),
        "cdx_digest": row.get("digest"),
        "cdx_length": row.get("length"),
        "raw_snapshot_url": url,
    }
    try:
        response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
        result.update(
            {
                "http_status": response.status_code,
                "final_url": response.url,
                "content_type": response.headers.get("content-type"),
                "redirect_chain": [
                    {
                        "status": item.status_code,
                        "url": item.url,
                        "location": item.headers.get("location"),
                    }
                    for item in response.history
                ],
            }
        )
        response.raise_for_status()
        payload = response.content
        if len(payload) < 300:
            raise RuntimeError(f"payload too small: {len(payload)} bytes")
        soup = BeautifulSoup(payload, "html.parser")
        title = " ".join(soup.title.stripped_strings) if soup.title else ""
        body_text = " ".join(soup.stripped_strings)
        identity_ok = has_candidate_identity(body_text, candidate)
        result.update(
            {
                "byte_length": len(payload),
                "sha256": sha256(payload),
                "page_title": title,
                "candidate_identity_present": identity_ok,
                "transfer_lexicon_hits": transfer_term_hits(body_text),
                "bounded_text_excerpt": bounded_snippet(body_text, candidate),
            }
        )
        if not identity_ok:
            result["status"] = "REJECTED_IDENTITY_NOT_PRESENT"
            return result, None
        result["status"] = "RAW_OFFICIAL_PAGE_CANDIDATE"
        return result, payload
    except Exception as exc:
        result.update(
            {
                "status": "FETCH_FAIL",
                "error": f"{type(exc).__name__}: {exc}",
            }
        )
        return result, None


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw_dir = OUT / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    target_records = []
    operational_failures = []
    saved_sha256: set[str] = set()

    for target in TARGETS:
        target_rec = {
            "candidate": target["candidate"],
            "target_club": target["target_club"],
            "window_from": target["window_from"],
            "window_to": target["window_to"],
            "scope_note": target.get("scope_note"),
            "sources": [],
        }
        accepted_for_target = 0

        for source in target["sources"]:
            source_rec = {
                "authority": source["authority"],
                "source_role": source["role"],
                "hosts": source["hosts"],
                "url_token": source["url_token"],
                "cdx_queries": [],
                "cdx_rows_total": 0,
                "attempts": [],
            }
            rows_by_key: dict[tuple[str, str, str], dict] = {}

            for host in source["hosts"]:
                rows, query_records = discover_rows(
                    session,
                    host,
                    source["url_token"],
                    target["window_from"],
                    target["window_to"],
                )
                source_rec["cdx_queries"].extend(query_records)
                for query_record in query_records:
                    if query_record.get("status") == "FAIL":
                        operational_failures.append(
                            {
                                "candidate": target["candidate"],
                                "authority": source["authority"],
                                "host": host,
                                "mode": query_record["mode"],
                                "error": query_record["error"],
                            }
                        )
                for row in rows:
                    key = (
                        str(row.get("timestamp") or ""),
                        str(row.get("original") or ""),
                        str(row.get("digest") or ""),
                    )
                    rows_by_key[key] = row
                time.sleep(SLEEP_SECONDS)

            ordered_rows = sorted(
                rows_by_key.values(),
                key=lambda row: (
                    str(row.get("timestamp") or ""),
                    str(row.get("original") or ""),
                ),
            )
            source_rec["cdx_rows_total"] = len(ordered_rows)

            unique_payloads_for_source = 0
            for row in ordered_rows[:MAX_FETCHES_PER_SOURCE]:
                attempt, payload = fetch_candidate(
                    session,
                    row,
                    target["candidate"],
                    source["authority"],
                    source["role"],
                )
                if payload is not None:
                    digest = attempt["sha256"]
                    if digest in saved_sha256:
                        attempt["raw_file"] = None
                        attempt["duplicate_payload_sha256"] = True
                    else:
                        filename = safe_filename(
                            target["candidate"],
                            source["authority"],
                            str(row.get("timestamp") or ""),
                            str(row.get("digest") or ""),
                        )
                        (raw_dir / filename).write_bytes(payload)
                        attempt["raw_file"] = f"raw/{filename}"
                        attempt["duplicate_payload_sha256"] = False
                        saved_sha256.add(digest)
                        unique_payloads_for_source += 1
                    accepted_for_target += 1
                source_rec["attempts"].append(attempt)
                time.sleep(SLEEP_SECONDS)

            source_rec["raw_official_page_candidates"] = sum(
                1
                for attempt in source_rec["attempts"]
                if attempt.get("status") == "RAW_OFFICIAL_PAGE_CANDIDATE"
            )
            source_rec["unique_raw_payloads_saved"] = unique_payloads_for_source

            successful_queries = [
                q for q in source_rec["cdx_queries"] if q.get("status") == "PASS"
            ]
            if source_rec["raw_official_page_candidates"]:
                source_rec["status"] = "RAW_OFFICIAL_PAGE_CANDIDATE_FOUND"
            elif ordered_rows:
                source_rec["status"] = "CDX_ROWS_FOUND_BUT_NO_IDENTITY_VALID_PAGE"
            elif successful_queries:
                source_rec["status"] = "NO_CDX_ROW_FOUND"
            else:
                source_rec["status"] = "CDX_QUERY_FAILED"
            target_rec["sources"].append(source_rec)

        target_rec["raw_official_page_candidates"] = accepted_for_target
        target_rec["status"] = (
            "RAW_OFFICIAL_PAGE_CANDIDATE_FOUND"
            if accepted_for_target
            else "NO_ARCHIVED_OFFICIAL_PAGE_CANDIDATE_FOUND"
        )
        target_records.append(target_rec)

    successful_cdx_queries = sum(
        1
        for target in target_records
        for source in target["sources"]
        for query in source["cdx_queries"]
        if query.get("status") == "PASS"
    )
    raw_candidate_count = sum(
        target["raw_official_page_candidates"] for target in target_records
    )
    resolved_candidate_count = sum(
        1
        for target in target_records
        if target["status"] == "RAW_OFFICIAL_PAGE_CANDIDATE_FOUND"
    )

    if successful_cdx_queries == 0:
        overall_status = "FAIL_CLOSED_NO_SUCCESSFUL_CDX_QUERY"
    elif resolved_candidate_count == len(TARGETS):
        overall_status = "PASS_RAW_CANDIDATES_FOR_ALL_TARGETS"
    else:
        overall_status = "PASS_ACQUISITION_WITH_UNRESOLVED_TARGETS"

    manifest = {
        "schema": "NEXUS_HISTORICAL_RESIDUAL_10_WAYBACK_RAW_ACQUISITION_V1",
        "generated_at": (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
        "scope": "2018_19_PRIORITY_RESIDUAL_10_OFFICIAL_ARCHIVE_DISCOVERY",
        "authority_policy": {
            "accepted_domains": "FIRST_PARTY_CLUB_DOMAINS_ONLY",
            "custodian": "INTERNET_ARCHIVE_WAYBACK_MACHINE",
            "raw_bytes_preferred": True,
            "sha256_each_saved_payload": True,
            "semantic_transfer_claims_created": False,
            "canonical_fields_created": False,
            "replay_admissibility_created": False,
            "discovery_source_text_used_as_evidence": False,
            "absence_of_archive_is_absence_of_transfer": False,
            "identity_validation": (
                "ALL_NORMALIZED_PLAYER_NAME_TOKENS_MUST_APPEAR_IN_ARCHIVED_PAGE_TEXT"
            ),
            "tls_verification_disabled": False,
        },
        "limits": {
            "max_cdx_rows_per_query": MAX_CDX_ROWS,
            "max_fetches_per_source": MAX_FETCHES_PER_SOURCE,
        },
        "summary": {
            "target_count": len(TARGETS),
            "targets_with_raw_official_page_candidate": resolved_candidate_count,
            "targets_without_raw_official_page_candidate": (
                len(TARGETS) - resolved_candidate_count
            ),
            "raw_official_page_candidate_attempts": raw_candidate_count,
            "unique_raw_payloads_saved": len(saved_sha256),
            "successful_cdx_queries": successful_cdx_queries,
            "operational_failure_count": len(operational_failures),
        },
        "targets": target_records,
        "operational_failures": operational_failures,
        "status": overall_status,
    }

    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))

    if overall_status.startswith("FAIL_CLOSED"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
