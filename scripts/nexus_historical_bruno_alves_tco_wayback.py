from __future__ import annotations

import hashlib
import json
import os
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path(os.environ.get("NEXUS_BRUNO_ALVES_OUT", ".nexus-historical-bruno-alves-exact"))
TIMEOUT = float(os.environ.get("NEXUS_REQUEST_TIMEOUT_SECONDS", "25"))
USER_AGENT = "FantaNexus-Historical-Bruno-Alves-Wayback/1.1"
SHORT_URL = "https://t.co/GbiQO0i3ZC"

TARGET = {
    "candidate": "Bruno Alves",
    "subjectId": "historical:2018-19:1864",
    "targetClubCode": "PAR",
    "tweetDate": "2018-07-12",
}

REQUIRED_NORMALIZED_TERMS = [
    "bruno eduardo regufe alves",
    "parma calcio 1913",
    "rangers fc",
    "svincolato",
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def availability(session: requests.Session, url: str, timestamp: str) -> dict:
    api = f"https://archive.org/wayback/available?url={quote(url, safe='')}&timestamp={timestamp}"
    r = session.get(api, timeout=TIMEOUT)
    r.raise_for_status()
    return {"api_url": api, "payload": r.json()}


def raw_snapshot_url(snapshot_url: str, timestamp: str) -> str:
    marker = f"/web/{timestamp}/"
    if marker in snapshot_url:
        return snapshot_url.replace(marker, f"/web/{timestamp}id_/", 1)
    marker = f"/web/{timestamp}if_/"
    if marker in snapshot_url:
        return snapshot_url.replace(marker, f"/web/{timestamp}id_/", 1)
    original = snapshot_url.split("/web/", 1)[-1].split("/", 1)[-1]
    return f"https://web.archive.org/web/{timestamp}id_/{original}"


def official_candidates(resolve: requests.Response) -> list[str]:
    urls: list[str] = []
    for h in resolve.history:
        location = h.headers.get("location")
        if location and "parmacalcio1913.com" in location.lower() and "404.php" not in location.lower():
            urls.append(location)
        if "parmacalcio1913.com" in h.url.lower() and "404.php" not in h.url.lower():
            urls.append(h.url)
    if "parmacalcio1913.com" in resolve.url.lower() and "404.php" not in resolve.url.lower():
        urls.append(resolve.url)

    expanded: list[str] = []
    for url in urls:
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if not path:
            continue
        for scheme in ("http", "https"):
            for host in ("parmacalcio1913.com", "www.parmacalcio1913.com"):
                expanded.append(f"{scheme}://{host}{path}")
                expanded.append(f"{scheme}://{host}{path}/")

    deduped = []
    seen = set()
    for url in urls + expanded:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    raw_dir = OUT / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    rec = dict(TARGET)
    failures = []
    try:
        resolve = session.get(SHORT_URL, timeout=TIMEOUT, allow_redirects=True)
        rec["short_url"] = SHORT_URL
        rec["short_url_status"] = resolve.status_code
        rec["short_url_final_url"] = resolve.url
        rec["short_url_redirect_chain"] = [
            {"status": h.status_code, "url": h.url, "location": h.headers.get("location")}
            for h in resolve.history
        ]

        candidates = official_candidates(resolve)
        if not candidates:
            raise RuntimeError("short URL redirect chain exposed no non-404 official Parma URL")
        rec["official_url_candidates_from_redirect_chain"] = candidates

        probes = []
        chosen = None
        chosen_official_url = None
        for official_url in candidates:
            for timestamp in (
                "20180712000000",
                "20180713000000",
                "20180720000000",
                "20180801000000",
                "20181231000000",
            ):
                try:
                    avail = availability(session, official_url, timestamp)
                    closest = avail["payload"].get("archived_snapshots", {}).get("closest") or {}
                    probes.append(
                        {
                            "official_url": official_url,
                            "requested_timestamp": timestamp,
                            "api_url": avail["api_url"],
                            "closest": closest,
                            "status": "PASS",
                        }
                    )
                    if closest.get("available") is True and str(closest.get("status")) == "200":
                        capture_ts = str(closest.get("timestamp") or "")
                        archived_original = str(closest.get("url") or "").lower()
                        if capture_ts.startswith("2018") and "parmacalcio1913.com" in archived_original:
                            chosen = closest
                            chosen_official_url = official_url
                            break
                except Exception as exc:
                    probes.append(
                        {
                            "official_url": official_url,
                            "requested_timestamp": timestamp,
                            "status": "FAIL",
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                time.sleep(0.15)
            if chosen:
                break
        rec["availability_probes"] = probes
        if not chosen or not chosen_official_url:
            raise RuntimeError("no 2018 Wayback capture found for any official Parma slug variant")
        rec["resolved_official_url"] = chosen_official_url

        capture_ts = str(chosen["timestamp"])
        snap = str(chosen["url"])
        raw_url = raw_snapshot_url(snap, capture_ts)
        response = session.get(raw_url, timeout=TIMEOUT, allow_redirects=True)
        response.raise_for_status()
        data = response.content
        if len(data) < 500:
            raise RuntimeError(f"payload too small: {len(data)} bytes")
        soup = BeautifulSoup(data, "html.parser")
        title = " ".join(soup.title.stripped_strings) if soup.title else ""
        text = " ".join(soup.stripped_strings)
        normalized = normalize(text)
        missing = [term for term in REQUIRED_NORMALIZED_TERMS if normalize(term) not in normalized]
        if missing:
            raise RuntimeError(f"required first-party semantic terms missing: {missing}")

        compact = " ".join(text.split())
        idx = normalize(compact).find("bruno eduardo regufe alves")
        excerpt = compact[max(0, idx - 900): idx + 2400] if idx >= 0 else compact[:3300]

        filename = f"historical_2018-19_1864__{capture_ts}.html"
        (raw_dir / filename).write_bytes(data)
        rec.update(
            {
                "status": "PASS",
                "capture_timestamp": capture_ts,
                "snapshot_url": snap,
                "raw_snapshot_url": raw_url,
                "raw_final_url": response.url,
                "raw_redirect_chain": [
                    {"status": h.status_code, "url": h.url, "location": h.headers.get("location")}
                    for h in response.history
                ],
                "content_type": response.headers.get("content-type"),
                "byte_length": len(data),
                "sha256": sha256(data),
                "page_title": title,
                "required_semantic_terms": REQUIRED_NORMALIZED_TERMS,
                "bounded_text_excerpt": excerpt,
                "raw_file": f"raw/{filename}",
            }
        )
    except Exception as exc:
        rec.update({"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})
        failures.append(rec["error"])

    manifest = {
        "schema": "NEXUS_HISTORICAL_BRUNO_ALVES_TCO_WAYBACK_V1_1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "authority": "ARCHIVED_FIRST_PARTY_CLUB_PAGE_IF_PASS",
        "custodian": "INTERNET_ARCHIVE_WAYBACK_MACHINE",
        "short_link_and_redirect_chain_are_discovery_only": True,
        "semantic_event_acceptance_performed": False,
        "knownAt_created": False,
        "replay_admissibility_created": False,
        "record": rec,
        "status": "PASS" if not failures else "FAIL_CLOSED",
        "failures": failures,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, ensure_ascii=False))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
