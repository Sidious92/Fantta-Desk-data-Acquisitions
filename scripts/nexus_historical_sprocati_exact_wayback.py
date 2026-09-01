from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path

import requests
from bs4 import BeautifulSoup


OUT = Path(
    os.environ.get(
        "NEXUS_SPROCATI_EXACT_OUT",
        ".nexus-historical-sprocati-exact",
    )
)
TIMEOUT = float(os.environ.get("NEXUS_REQUEST_TIMEOUT_SECONDS", "35"))
USER_AGENT = "FantaNexus-Historical-Sprocati-Exact-Wayback/1.0"

TARGET = {
    "candidate": "Mattia Sprocati",
    "subjectId": "historical:2018-19:2773",
    "targetClubCode": "LAZ",
    "publicationDate": "2018-06-29",
    "discovery_note": (
        "The exact official press-release path was recovered from the archived "
        "first-party S.S. Lazio news index. The index and any external citations "
        "are discovery-only and contribute no canonical transfer field."
    ),
}

PAGES = [
    {
        "role": "OFFICIAL_DESTINATION_CLUB_PRESS_RELEASE",
        "capture_timestamp": "20220529023108",
        "original_url": (
            "https://www.sslazio.it/it/news/press-release-2/"
            "47399-comunicato-29-06-2018"
        ),
        "required_normalized_terms": [
            "s s lazio",
            "acquisito a titolo definitivo",
            "sprocati mattia",
            "u s salernitana",
            "contratto di durata quinquennale",
        ],
        "excerpt_needle": "Sprocati Mattia",
    },
    {
        "role": "OFFICIAL_DESTINATION_CLUB_PLAYER_INTRODUCTION",
        "capture_timestamp": "20180801190242",
        "original_url": (
            "http://www.sslazio.it/it/news/ultime-news/"
            "47389-benvenutomattia-alla-scoperta-di-sprocati-nuovo-acquisto-biancoceleste"
        ),
        "required_normalized_terms": [
            "mattia sprocati",
            "ufficialmente un calciatore",
            "squadra precedente u s salernitana",
        ],
        "excerpt_needle": "Mattia Sprocati",
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


def bounded_excerpt(text: str, needle: str, radius: int = 1400) -> str:
    compact = " ".join(text.split())
    normalized = normalize(compact)
    pos = normalized.find(normalize(needle))
    if pos < 0:
        return compact[: 2 * radius]
    start = max(0, pos - radius)
    end = min(len(compact), pos + radius)
    return compact[start:end]


def raw_snapshot_url(page: dict) -> str:
    return (
        f"https://web.archive.org/web/{page['capture_timestamp']}id_/"
        f"{page['original_url']}"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw_dir = OUT / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    records = []
    failures = []
    for index, page in enumerate(PAGES, start=1):
        raw_url = raw_snapshot_url(page)
        rec = {
            "role": page["role"],
            "capture_timestamp": page["capture_timestamp"],
            "original_url": page["original_url"],
            "raw_snapshot_url": raw_url,
        }
        try:
            response = session.get(raw_url, timeout=TIMEOUT, allow_redirects=True)
            response.raise_for_status()
            data = response.content
            if len(data) < 500:
                raise RuntimeError(f"payload too small: {len(data)} bytes")

            soup = BeautifulSoup(data, "html.parser")
            title = " ".join(soup.title.stripped_strings) if soup.title else ""
            text = " ".join(soup.stripped_strings)
            normalized_text = normalize(text)
            missing = [
                term
                for term in page["required_normalized_terms"]
                if normalize(term) not in normalized_text
            ]
            if missing:
                raise RuntimeError(
                    f"required first-party semantic terms missing: {missing}"
                )

            filename = (
                f"historical_2018-19_2773__{index}__"
                f"{page['capture_timestamp']}.html"
            )
            (raw_dir / filename).write_bytes(data)
            rec.update(
                {
                    "status": "PASS",
                    "final_url": response.url,
                    "redirect_chain": [
                        {
                            "status": item.status_code,
                            "url": item.url,
                            "location": item.headers.get("location"),
                        }
                        for item in response.history
                    ],
                    "content_type": response.headers.get("content-type"),
                    "byte_length": len(data),
                    "sha256": sha256(data),
                    "page_title": title,
                    "required_semantic_terms": page[
                        "required_normalized_terms"
                    ],
                    "bounded_text_excerpt": bounded_excerpt(
                        text,
                        page["excerpt_needle"],
                    ),
                    "raw_file": f"raw/{filename}",
                }
            )
        except Exception as exc:
            rec.update(
                {
                    "status": "FAIL",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            failures.append(
                {
                    "role": page["role"],
                    "error": rec["error"],
                }
            )
        records.append(rec)

    manifest = {
        "schema": "NEXUS_HISTORICAL_SPROCATI_EXACT_WAYBACK_V1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "authority": "ARCHIVED_FIRST_PARTY_CLUB_PAGES",
        "custodian": "INTERNET_ARCHIVE_WAYBACK_MACHINE",
        "discovery_source_used_as_evidence": False,
        "semantic_event_acceptance_performed": False,
        "archived_lega_ambiguity_resolved": False,
        "knownAt_created": False,
        "effectiveAt_created": False,
        "replay_admissibility_created": False,
        "target": TARGET,
        "records": records,
        "status": "PASS" if not failures else "FAIL_CLOSED",
        "failures": failures,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
