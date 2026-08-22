#!/usr/bin/env python3
"""Bounded probe of FotMob player-search contract using four pre-verified IDs.

The probe establishes only whether the public FotMob search surface can recover
an already-known exact FotMob player ID when queried with that player's canonical
name read from the exact player page. It does NOT resolve any D1 subject.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import traceback
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

PLAYERS = [1190371, 1024432, 1529483, 1379468]
UA = "FantaNexus-D1-FotMobSearchProbe/1.0 (+https://github.com/Sidious92/Fantta-Desk-data-Acquisitions)"
SCRIPT_RE = re.compile(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.I | re.S)
SEARCH_TEMPLATE = "https://www.fotmob.com/api/search/suggest?term={term}"


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(b: bytes):
    return hashlib.sha256(b).hexdigest()


def fetch(url: str, accept: str, attempts: int = 6):
    last = None
    for i in range(attempts):
        req = Request(url, headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en;q=0.8", "Cache-Control": "no-cache"})
        try:
            with urlopen(req, timeout=45) as r:
                return int(getattr(r, "status", 200)), dict(r.headers.items()), r.read()
        except HTTPError as e:
            last = f"HTTP {e.code}: {e.reason}"
            if e.code not in {429, 500, 502, 503, 504}:
                raise
            retry = (e.headers or {}).get("Retry-After")
            delay = int(retry) if retry and str(retry).isdigit() else min(20, 2 ** i)
        except URLError as e:
            last = f"URL error: {e.reason}"
            delay = min(20, 2 ** i)
        if i + 1 < attempts:
            time.sleep(max(1, delay))
    raise RuntimeError(last or "FETCH_FAILED")


def walk(obj, path="$"):
    if isinstance(obj, dict):
        yield path, obj
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def scalar_id_values(d: dict):
    out = []
    for k, v in d.items():
        nk = re.sub(r"[^a-z0-9]", "", str(k).lower())
        if nk in {"id", "playerid", "fotmobid", "fotmobplayerid"} and not isinstance(v, (dict, list)):
            out.append((k, str(v)))
    return out


def player_page(pid: int, out: Path):
    url = f"https://www.fotmob.com/players/{pid}/x"
    st, headers, raw = fetch(url, "text/html,application/xhtml+xml,*/*;q=0.8")
    text = raw.decode("utf-8", errors="replace")
    m = SCRIPT_RE.search(text)
    if not m:
        raise RuntimeError(f"NEXT_DATA_NOT_FOUND_{pid}")
    nd = json.loads(unescape(m.group(1)))
    data = (((nd.get("props") or {}).get("pageProps") or {}).get("data") or {})
    person = ((data.get("meta") or {}).get("personJSONLD") or {})
    name = person.get("name")
    if not isinstance(name, str) or not name.strip():
        # fail closed rather than using an arbitrary page label
        raise RuntimeError(f"CANONICAL_PERSON_NAME_NOT_FOUND_{pid}")
    canonical = (json.dumps(nd, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
    p = out / "raw" / f"player-{pid}-next-data.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(canonical)
    return {
        "fotmobPlayerId": pid,
        "canonicalName": name.strip(),
        "playerPage": {"url": url, "httpStatus": st, "htmlBytes": len(raw), "htmlSha256": sha(raw), "nextDataPath": str(p.relative_to(out)), "nextDataBytes": len(canonical), "nextDataSha256": sha(canonical), "contentType": headers.get("Content-Type")},
    }


def search_known(rec: dict, out: Path):
    term = quote(rec["canonicalName"], safe="")
    url = SEARCH_TEMPLATE.format(term=term)
    st, headers, raw = fetch(url, "application/json,text/plain,*/*")
    p = out / "raw" / f"search-{rec['fotmobPlayerId']}.json"
    p.write_bytes(raw)
    payload = json.loads(raw)
    matches = []
    for path, obj in walk(payload):
        ids = scalar_id_values(obj)
        if any(v == str(rec["fotmobPlayerId"]) for _, v in ids):
            matches.append({"path": path, "idFields": [{"key": k, "value": v} for k, v in ids], "objectKeys": sorted(obj.keys()), "object": obj})
    return {
        **rec,
        "search": {
            "url": url,
            "httpStatus": st,
            "contentType": headers.get("Content-Type"),
            "rawPath": str(p.relative_to(out)),
            "bytes": len(raw),
            "sha256": sha(raw),
            "exactKnownIdMatchCount": len(matches),
            "exactKnownIdMatches": matches,
        },
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    records = []
    failures = []
    for pid in PLAYERS:
        try:
            records.append(search_known(player_page(pid, out), out))
        except Exception as e:
            failures.append({"fotmobPlayerId": pid, "errorType": type(e).__name__, "detail": str(e), "traceback": traceback.format_exc()[-10000:]})

    pass_count = sum(1 for r in records if r["search"]["exactKnownIdMatchCount"] >= 1)
    # Record candidate match paths. A common path shape is evidence for stable schema,
    # but exact ID recovery for all four is the hard gate.
    path_sets = []
    for r in records:
        path_sets.append({m["path"] for m in r["search"]["exactKnownIdMatches"]})
    common_paths = sorted(set.intersection(*path_sets)) if len(path_sets) == 4 and all(path_sets) else []
    status = "PASS" if len(records) == 4 and not failures and pass_count == 4 else "INSUFFICIENT_EVIDENCE"

    result = {
        "schema": "NEXUS_D1_FOTMOB_SEARCH_CONTRACT_PROBE_V1",
        "protocolVersion": "1.1",
        "status": status,
        "capturedAt": now(),
        "endpoint": SEARCH_TEMPLATE,
        "summary": {"subjectsExpected": 4, "subjectsFetched": len(records), "technicalFailures": len(failures), "exactKnownIdRecovered": pass_count, "commonExactIdObjectPaths": common_paths},
        "rules": {"d1SubjectsResolved": False, "nameOnlyIdentityAccepted": False, "fuzzyMatchingUsed": False, "dobUsedForIdentitySelection": False, "computedAgeDerived": False, "trainingPromotionGranted": False, "f1Started": False, "d2Started": False},
        "failures": failures,
        "records": records,
    }
    (out / "RESULT.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    files = []
    for p in sorted(x for x in out.rglob("*") if x.is_file() and x.name != "MANIFEST.json"):
        b = p.read_bytes()
        files.append({"path": str(p.relative_to(out)), "size": len(b), "sha256": sha(b)})
    digest = sha("\n".join(f"{x['path']}\t{x['size']}\t{x['sha256']}" for x in files).encode())
    (out / "MANIFEST.json").write_text(json.dumps({"schema": "NEXUS_D1_FOTMOB_SEARCH_CONTRACT_PROBE_MANIFEST_V1", "generatedAt": now(), "status": status, "files": files, "fileCount": len(files), "canonicalContentSha256": digest, "rules": result["rules"]}, indent=2) + "\n")
    print(json.dumps({"status": status, "summary": result["summary"]}, indent=2))
    if failures:
        raise SystemExit(2)
    if status != "PASS":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
