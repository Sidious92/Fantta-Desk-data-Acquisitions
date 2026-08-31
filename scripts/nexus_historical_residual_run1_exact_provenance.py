from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import requests

OUT = Path(os.environ.get("NEXUS_RESIDUAL_EXACT_OUT", ".nexus-historical-residual-exact"))
TIMEOUT = float(os.environ.get("NEXUS_REQUEST_TIMEOUT_SECONDS", "20"))
USER_AGENT = "FantaNexus-Historical-Residual-Exact-Provenance/1.0"

TARGETS = [
    {
        "candidate": "Lorenzo Dickmann",
        "subjectId": "historical:2018-19:2787",
        "capture_timestamp": "20180628153217",
        "original_url": "http://www.spalferrara.it/lorenzo-dickmann-arriva-alla-spal-prestito-dal-novara/",
        "expected_sha256": "9bb28d31a3d22b397d48bff51a947d69d5487c8da9a9d5d20dc16373b65332bf",
    },
    {
        "candidate": "Johan Djourou",
        "subjectId": "historical:2018-19:2831",
        "capture_timestamp": "20180721221711",
        "original_url": "http://www.spalferrara.it/johan-djourou-un-giocatore-della-spal/",
        "expected_sha256": "d048f0b35a33ec506d3b4c52bff9fe9bbd08b62ad8ed329feeb8ef96ba76ecb2",
    },
    {
        "candidate": "Alban Lafont",
        "subjectId": "historical:2018-19:2387",
        "capture_timestamp": "20180702233230",
        "original_url": "http://it.violachannel.tv/vc13-dettaglio-breaking/items/id-02-07-2018_16-55-25_lafont-e-un-calciatore-della-fiorentina.html",
        "expected_sha256": "23a707bfd29b8c4b6b85e71c049877586b3cd926cc7650a865b41cb2eb54df98",
    },
    {
        "candidate": "Jacob Rasmussen",
        "subjectId": "historical:2018-19:2752",
        "capture_timestamp": "20180705175657",
        "original_url": "http://www.rbk.no/nyheter/rasmussen-solgt-til-empoli",
        "expected_sha256": "e701e267f9ded821d5de101fd8cf383922f2a051f13a1b6789a962aa7b137e28",
    },
]

CDX_FIELDS = ["timestamp", "original", "statuscode", "mimetype", "digest", "length"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cdx_exact(session: requests.Session, target: dict) -> tuple[str, dict]:
    day = target["capture_timestamp"][:8]
    params = {
        "url": target["original_url"],
        "output": "json",
        "fl": ",".join(CDX_FIELDS),
        "filter": "statuscode:200",
        "from": day,
        "to": day,
        "limit": "100",
    }
    url = "https://web.archive.org/cdx/search/cdx?" + urlencode(params)
    response = session.get(url, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        raise RuntimeError("CDX returned no rows")
    if payload[0] != CDX_FIELDS:
        raise RuntimeError(f"unexpected CDX header: {payload[0]!r}")
    rows = [dict(zip(CDX_FIELDS, row)) for row in payload[1:] if len(row) == len(CDX_FIELDS)]
    matches = [row for row in rows if row["timestamp"] == target["capture_timestamp"]]
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one capture-timestamp match, got {len(matches)}")
    return url, matches[0]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw_dir = OUT / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    records = []
    failures = []
    for target in TARGETS:
        rec = dict(target)
        try:
            cdx_url, row = cdx_exact(session, target)
            if row["original"] != target["original_url"]:
                raise RuntimeError(f"CDX original mismatch: {row['original']!r}")
            raw_url = f"https://web.archive.org/web/{target['capture_timestamp']}id_/{row['original']}"
            response = session.get(raw_url, timeout=TIMEOUT, allow_redirects=True)
            response.raise_for_status()
            data = response.content
            actual_sha = sha256(data)
            if actual_sha != target["expected_sha256"]:
                raise RuntimeError(f"raw SHA mismatch: {actual_sha} != {target['expected_sha256']}")
            filename = f"{target['subjectId'].replace(':', '_')}__{target['capture_timestamp']}.html"
            (raw_dir / filename).write_bytes(data)
            rec.update(
                {
                    "status": "PASS",
                    "cdx_query_url": cdx_url,
                    "cdx": row,
                    "raw_snapshot_url": raw_url,
                    "final_url": response.url,
                    "redirect_chain": [
                        {"status": h.status_code, "url": h.url, "location": h.headers.get("location")}
                        for h in response.history
                    ],
                    "content_type": response.headers.get("content-type"),
                    "byte_length": len(data),
                    "sha256": actual_sha,
                    "raw_file": f"raw/{filename}",
                }
            )
        except Exception as exc:
            rec.update({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
            failures.append({"subjectId": target["subjectId"], "error": rec["error"]})
        records.append(rec)
        time.sleep(0.25)

    manifest = {
        "schema": "NEXUS_HISTORICAL_RESIDUAL_EXACT_ARCHIVE_PROVENANCE_V1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "authority": "ARCHIVED_FIRST_PARTY_CLUB_PAGE",
        "custodian": "INTERNET_ARCHIVE_WAYBACK_MACHINE",
        "semantic_event_acceptance_performed": False,
        "knownAt_created": False,
        "replay_admissibility_created": False,
        "records": records,
        "status": "PASS" if not failures else "FAIL_CLOSED",
        "failures": failures,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
