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

OUT = Path(os.environ.get("NEXUS_TANASIJEVIC_EXACT_OUT", ".nexus-historical-tanasijevic-exact"))
TIMEOUT = float(os.environ.get("NEXUS_REQUEST_TIMEOUT_SECONDS", "25"))
USER_AGENT = "FantaNexus-Historical-Tanasijevic-Exact-Wayback/1.0"

TARGET = {
    "candidate": "Strahinja Tanasijevic",
    "subjectId": "historical:2018-19:2663",
    "targetClubCode": "CHI",
    "capture_timestamp": "20180621164956",
    "original_url": "http://www.chievoverona.it/it/primo-piano/news/ufficiale-strahinja-tanasijevic-%C3%A8-giallobl%C3%B9",
    "discovery_note": (
        "Exact archived first-party URL and capture timestamp were located through an indexed historical citation. "
        "The citation is discovery-only and contributes no canonical event field."
    ),
}

REQUIRED_NORMALIZED_TERMS = [
    "strahinja tanasijevic",
    "chievoverona",
    "fk rad belgrado",
    "diritto di opzione",
    "acquisizione a titolo definitivo",
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


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw_dir = OUT / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    raw_url = (
        f"https://web.archive.org/web/{TARGET['capture_timestamp']}id_/"
        f"{TARGET['original_url']}"
    )
    rec = dict(TARGET)
    rec["raw_snapshot_url"] = raw_url
    failures = []

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

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
        missing = [term for term in REQUIRED_NORMALIZED_TERMS if normalize(term) not in normalized_text]
        if missing:
            raise RuntimeError(f"required first-party semantic terms missing: {missing}")

        filename = f"historical_2018-19_2663__{TARGET['capture_timestamp']}.html"
        (raw_dir / filename).write_bytes(data)
        rec.update(
            {
                "status": "PASS",
                "final_url": response.url,
                "redirect_chain": [
                    {"status": h.status_code, "url": h.url, "location": h.headers.get("location")}
                    for h in response.history
                ],
                "content_type": response.headers.get("content-type"),
                "byte_length": len(data),
                "sha256": sha256(data),
                "page_title": title,
                "required_semantic_terms": REQUIRED_NORMALIZED_TERMS,
                "bounded_text_excerpt": bounded_excerpt(text, "Strahinja Tanasijevic"),
                "raw_file": f"raw/{filename}",
            }
        )
    except Exception as exc:
        rec.update({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        failures.append(rec["error"])

    manifest = {
        "schema": "NEXUS_HISTORICAL_TANASIJEVIC_EXACT_WAYBACK_V1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "authority": "ARCHIVED_FIRST_PARTY_CLUB_PAGE",
        "custodian": "INTERNET_ARCHIVE_WAYBACK_MACHINE",
        "discovery_source_used_as_evidence": False,
        "semantic_event_acceptance_performed": False,
        "knownAt_created": False,
        "replay_admissibility_created": False,
        "record": rec,
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
