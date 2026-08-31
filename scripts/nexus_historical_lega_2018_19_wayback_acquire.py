from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup

OUT = Path(os.environ.get("NEXUS_HIST_LEGA_2018_19_OUT", ".nexus-historical-lega-2018-19-wayback"))
TIMEOUT = float(os.environ.get("NEXUS_REQUEST_TIMEOUT_SECONDS", "60"))
USER_AGENT = "FantaNexus-Historical-Lega-Recovery/1.2"

TARGETS = [
    {
        "period": "SUMMER",
        "capture_timestamp": "20190220002802",
        "cdx_digest": "2JZK7WDKNEDAEYK3ZWAKFPYKXKP2M55A",
        "source_url": "https://www.legaseriea.it/it/serie-a/calcio-mercato",
        "expected_data_rows": 521,
        "filename": "legaseriea-calcio-mercato-2018-19-summer-20190220002802.html",
    },
    {
        "period": "WINTER",
        "capture_timestamp": "20190202153813",
        "cdx_digest": "2MSZZX5D35JIDZ6QUNMSYBOXYGTO4IZN",
        "source_url": "https://www.legaseriea.it/it/serie-a/calcio-mercato",
        "expected_data_rows": 270,
        "filename": "legaseriea-calcio-mercato-2018-19-winter-20190202153813.html",
    },
]

REQUIRED_HEADERS = ["DATA", "CALCIATORE", "PROVENIENZA", "DESTINAZIONE", "TIPO. TRASF"]
CDX_FIELDS = ["timestamp", "original", "statuscode", "mimetype", "digest", "length"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_market_html(payload: bytes, expected_rows: int) -> tuple[int, str]:
    if len(payload) < 1000:
        raise RuntimeError(f"payload too small: {len(payload)} bytes")
    soup = BeautifulSoup(payload, "html.parser")
    title = " ".join(soup.title.stripped_strings) if soup.title else ""
    if "Calciomercato" not in title:
        raise RuntimeError(f"unexpected page title: {title!r}")
    candidates = []
    for table in soup.find_all("table"):
        headers = [" ".join(th.stripped_strings).upper() for th in table.find_all("th")]
        header_blob = " | ".join(headers)
        if all(required in header_blob for required in REQUIRED_HEADERS):
            candidates.append(table)
    if len(candidates) != 1:
        raise RuntimeError(f"expected exactly one market table, found {len(candidates)}")
    row_count = len(candidates[0].find_all("tr")) - 1
    if row_count != expected_rows:
        raise RuntimeError(f"market row-count mismatch: {row_count} != {expected_rows}")
    return row_count, title


def cdx_exact_matches(session: requests.Session, target: dict) -> tuple[str, list[dict]]:
    day = target["capture_timestamp"][:8]
    params = {
        "url": "www.legaseriea.it/it/serie-a/calcio-mercato*",
        "output": "json",
        "fl": ",".join(CDX_FIELDS),
        "filter": "statuscode:200",
        "from": day,
        "to": day,
        "limit": "1000",
    }
    cdx_url = "https://web.archive.org/cdx/search/cdx?" + urlencode(params)
    response = session.get(cdx_url, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("CDX returned no rows")
    header = payload[0]
    if header != CDX_FIELDS:
        raise RuntimeError(f"unexpected CDX header: {header!r}")
    rows = [dict(zip(header, row)) for row in payload[1:] if len(row) == len(header)]
    matches = [
        row for row in rows
        if row["timestamp"] == target["capture_timestamp"] and row["digest"] == target["cdx_digest"]
    ]
    return cdx_url, matches


def fallback_snapshot_urls(target: dict) -> list[str]:
    ts = target["capture_timestamp"]
    path = "www.legaseriea.it/it/serie-a/calcio-mercato"
    return [
        f"https://web.archive.org/web/{ts}id_/https://{path}",
        f"https://web.archive.org/web/{ts}id_/http://{path}",
    ]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    records = []
    failures = []
    for target in TARGETS:
        rec = dict(target)
        cdx_url = None
        cdx_matches = []
        cdx_error = None
        try:
            cdx_url, cdx_matches = cdx_exact_matches(session, target)
        except Exception as exc:
            cdx_error = f"{type(exc).__name__}: {exc}"
        rec["cdx_query_url"] = cdx_url
        rec["cdx_matches"] = cdx_matches
        if cdx_error:
            rec["cdx_error"] = cdx_error

        candidate_urls = []
        for row in cdx_matches:
            original = row["original"]
            candidate_urls.append(
                f"https://web.archive.org/web/{target['capture_timestamp']}id_/{original}"
            )
        candidate_urls.extend(fallback_snapshot_urls(target))
        # stable dedupe preserving priority
        candidate_urls = list(dict.fromkeys(candidate_urls))

        attempts = []
        accepted = None
        last_error = None
        for snapshot_url in candidate_urls:
            attempt = {"snapshot_url": snapshot_url}
            try:
                response = session.get(snapshot_url, timeout=TIMEOUT, allow_redirects=True)
                attempt.update(
                    {
                        "http_status": response.status_code,
                        "final_url": response.url,
                        "content_type": response.headers.get("content-type"),
                    }
                )
                response.raise_for_status()
                payload = response.content
                row_count, title = validate_market_html(payload, target["expected_data_rows"])
                attempt.update(
                    {
                        "status": "PASS",
                        "byte_length": len(payload),
                        "sha256": sha256(payload),
                        "market_row_count": row_count,
                        "page_title": title,
                    }
                )
                accepted = (snapshot_url, response, payload, row_count, title)
                attempts.append(attempt)
                break
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                attempt.update({"status": "FAIL", "error": last_error})
                attempts.append(attempt)
        rec["attempts"] = attempts
        if accepted is None:
            rec.update({"status": "FAIL", "error": last_error or "no snapshot candidate succeeded"})
            failures.append({"period": target["period"], "error": rec["error"]})
        else:
            snapshot_url, response, payload, row_count, title = accepted
            path = OUT / target["filename"]
            path.write_bytes(payload)
            rec.update(
                {
                    "status": "PASS",
                    "accepted_snapshot_url": snapshot_url,
                    "final_url": response.url,
                    "content_type": response.headers.get("content-type"),
                    "byte_length": len(payload),
                    "sha256": sha256(payload),
                    "market_row_count": row_count,
                    "page_title": title,
                    "raw_file": target["filename"],
                }
            )
        records.append(rec)
        time.sleep(1.0)

    manifest = {
        "schema": "NEXUS_HISTORICAL_LEGA_2018_19_WAYBACK_RAW_ACQUISITION_V1_2",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "authority": "ARCHIVED_FIRST_PARTY_LEGA_SERIE_A_HTML",
        "custodian": "INTERNET_ARCHIVE_WAYBACK_MACHINE",
        "claim_complete_league_ledger": False,
        "allowed_use": "EVENT_SPECIFIC_EVIDENCE_ONLY",
        "validation": {
            "cdx_timestamp_and_digest_match_preferred": True,
            "page_title_contains": "Calciomercato",
            "required_market_headers": REQUIRED_HEADERS,
            "expected_data_rows": {t["period"]: t["expected_data_rows"] for t in TARGETS},
            "redirected_non_market_html": "FAIL_CLOSED",
        },
        "tls_verification_disabled": False,
        "records": records,
        "status": "PASS" if not failures else "FAIL_CLOSED",
        "failures": failures,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
