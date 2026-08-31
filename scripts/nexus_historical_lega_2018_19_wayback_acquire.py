from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

OUT = Path(os.environ.get("NEXUS_HIST_LEGA_2018_19_OUT", ".nexus-historical-lega-2018-19-wayback"))
TIMEOUT = float(os.environ.get("NEXUS_REQUEST_TIMEOUT_SECONDS", "60"))
USER_AGENT = "FantaNexus-Historical-Lega-Recovery/1.1"

TARGETS = [
    {
        "period": "SUMMER",
        "capture_timestamp": "20190220002802",
        "cdx_digest": "2JZK7WDKNEDAEYK3ZWAKFPYKXKP2M55A",
        "source_url": "https://www.legaseriea.it/it/serie-a/calcio-mercato",
        "snapshot_urls": [
            "https://web.archive.org/web/20190220002802id_/https://www.legaseriea.it/it/serie-a/calcio-mercato",
            "https://web.archive.org/web/20190220002802id_/http://www.legaseriea.it/it/serie-a/calcio-mercato",
        ],
        "expected_data_rows": 521,
        "filename": "legaseriea-calcio-mercato-2018-19-summer-20190220002802.html",
    },
    {
        "period": "WINTER",
        "capture_timestamp": "20190202153813",
        "cdx_digest": "2MSZZX5D35JIDZ6QUNMSYBOXYGTO4IZN",
        "source_url": "https://www.legaseriea.it/it/serie-a/calcio-mercato",
        "snapshot_urls": [
            "https://web.archive.org/web/20190202153813id_/https://www.legaseriea.it/it/serie-a/calcio-mercato",
            "https://web.archive.org/web/20190202153813id_/http://www.legaseriea.it/it/serie-a/calcio-mercato",
        ],
        "expected_data_rows": 270,
        "filename": "legaseriea-calcio-mercato-2018-19-winter-20190202153813.html",
    },
]

REQUIRED_HEADERS = ["DATA", "CALCIATORE", "PROVENIENZA", "DESTINAZIONE", "TIPO. TRASF"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_market_html(payload: bytes, expected_rows: int) -> tuple[int, str]:
    if len(payload) < 1000:
        raise RuntimeError(f"payload too small: {len(payload)} bytes")
    soup = BeautifulSoup(payload, "html.parser")
    title = " ".join(soup.title.stripped_strings) if soup.title else ""
    if "Calciomercato" not in title:
        raise RuntimeError(f"unexpected page title: {title!r}")
    tables = soup.find_all("table")
    candidates = []
    for table in tables:
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


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    records = []
    failures = []
    for target in TARGETS:
        rec = {k: v for k, v in target.items() if k != "snapshot_urls"}
        attempts = []
        accepted = None
        last_error = None
        for snapshot_url in target["snapshot_urls"]:
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
        "schema": "NEXUS_HISTORICAL_LEGA_2018_19_WAYBACK_RAW_ACQUISITION_V1_1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "authority": "ARCHIVED_FIRST_PARTY_LEGA_SERIE_A_HTML",
        "custodian": "INTERNET_ARCHIVE_WAYBACK_MACHINE",
        "claim_complete_league_ledger": False,
        "allowed_use": "EVENT_SPECIFIC_EVIDENCE_ONLY",
        "validation": {
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
