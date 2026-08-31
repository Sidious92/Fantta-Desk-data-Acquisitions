from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import requests

OUT = Path(os.environ.get("NEXUS_HIST_LEGA_2018_19_OUT", ".nexus-historical-lega-2018-19-wayback"))
TIMEOUT = float(os.environ.get("NEXUS_REQUEST_TIMEOUT_SECONDS", "60"))
USER_AGENT = "FantaNexus-Historical-Lega-Recovery/1.0"

TARGETS = [
    {
        "period": "SUMMER",
        "capture_timestamp": "20190220002802",
        "cdx_digest": "2JZK7WDKNEDAEYK3ZWAKFPYKXKP2M55A",
        "source_url": "https://www.legaseriea.it/it/serie-a/calcio-mercato",
        "snapshot_url": "https://web.archive.org/web/20190220002802id_/https://www.legaseriea.it/it/serie-a/calcio-mercato",
        "filename": "legaseriea-calcio-mercato-2018-19-summer-20190220002802.html",
    },
    {
        "period": "WINTER",
        "capture_timestamp": "20190202153813",
        "cdx_digest": "2MSZZX5D35JIDZ6QUNMSYBOXYGTO4IZN",
        "source_url": "https://www.legaseriea.it/it/serie-a/calcio-mercato",
        "snapshot_url": "https://web.archive.org/web/20190202153813id_/https://www.legaseriea.it/it/serie-a/calcio-mercato",
        "filename": "legaseriea-calcio-mercato-2018-19-winter-20190202153813.html",
    },
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    records = []
    failures = []
    for target in TARGETS:
        rec = dict(target)
        try:
            response = session.get(
                target["snapshot_url"],
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            rec.update(
                {
                    "http_status": response.status_code,
                    "final_url": response.url,
                    "content_type": response.headers.get("content-type"),
                }
            )
            response.raise_for_status()
            payload = response.content
            if len(payload) < 1000:
                raise RuntimeError(f"payload too small: {len(payload)} bytes")
            lower = payload[:4096].lower()
            if b"<html" not in lower and b"<!doctype html" not in lower:
                raise RuntimeError("payload is not recognizable HTML")

            path = OUT / target["filename"]
            path.write_bytes(payload)
            rec.update(
                {
                    "status": "PASS",
                    "byte_length": len(payload),
                    "sha256": sha256(payload),
                    "raw_file": target["filename"],
                }
            )
        except Exception as exc:
            rec.update({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
            failures.append({"period": target["period"], "error": rec["error"]})
        records.append(rec)
        time.sleep(1.0)

    manifest = {
        "schema": "NEXUS_HISTORICAL_LEGA_2018_19_WAYBACK_RAW_ACQUISITION_V1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "authority": "ARCHIVED_FIRST_PARTY_LEGA_SERIE_A_HTML",
        "custodian": "INTERNET_ARCHIVE_WAYBACK_MACHINE",
        "claim_complete_league_ledger": False,
        "allowed_use": "EVENT_SPECIFIC_EVIDENCE_ONLY",
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
