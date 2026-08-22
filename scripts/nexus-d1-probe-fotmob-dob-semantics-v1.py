#!/usr/bin/env python3
"""Bounded D1 probe of FotMob date-of-birth semantics on known exact player IDs.

This script is intentionally NOT an identity resolver. It only tests whether the
already-established FotMob player page contract exposes a stable, full date of
birth field under props.pageProps.data for four exact FotMob IDs.

Fail closed:
- no name/fuzzy search;
- no DOB used to establish identity;
- no age/year-only value accepted as DOB;
- no training/F1/D2 promotion;
- raw __NEXT_DATA__ payloads are retained and hashed.
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
from urllib.request import Request, urlopen

PLAYERS = [
    {"fotmobPlayerId": 1190371, "label": "Frigan"},
    {"fotmobPlayerId": 1024432, "label": "Adorante"},
    {"fotmobPlayerId": 1529483, "label": "Lisman"},
    {"fotmobPlayerId": 1379468, "label": "Rrahmani"},
]
UA = "FantaNexus-D1-FotMobDOBProbe/1.0 (+https://github.com/Sidious92/Fantta-Desk-data-Acquisitions)"
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ][0-9:.+\-Z]+)?$")
SCRIPT_RE = re.compile(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', re.I | re.S)


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def norm_key(k: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(k).lower())


def is_birth_key(k: str) -> bool:
    n = norm_key(k)
    return n in {"dob", "dateofbirth", "birthdate", "birthday", "birthdatetime"} or "birthdate" in n or "dateofbirth" in n


def valid_full_date(v):
    if not isinstance(v, str):
        return None
    m = DATE_RE.match(v.strip())
    if not m:
        return None
    y, mo, d = map(int, m.groups())
    try:
        datetime(y, mo, d)
    except ValueError:
        return None
    if not (1940 <= y <= 2010):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def walk(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}"
            yield p, k, v
            yield from walk(v, p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            p = f"{path}[{i}]"
            yield from walk(v, p)


def fetch(url: str, attempts: int = 5):
    last = None
    for i in range(attempts):
        req = Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
            "Cache-Control": "no-cache",
        })
        try:
            with urlopen(req, timeout=45) as r:
                raw = r.read()
                return int(getattr(r, "status", 200)), dict(r.headers.items()), raw
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


def get_data_root(next_data: dict):
    cur = next_data
    for k in ("props", "pageProps", "data"):
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur if isinstance(cur, dict) else None


def probe_player(spec: dict, out: Path):
    pid = int(spec["fotmobPlayerId"])
    url = f"https://www.fotmob.com/players/{pid}/x"
    captured = now()
    status, headers, html = fetch(url)
    html_sha = sha(html)
    text = html.decode("utf-8", errors="replace")
    m = SCRIPT_RE.search(text)
    if not m:
        raise RuntimeError(f"NEXT_DATA_NOT_FOUND_FOR_{pid}")
    payload_text = unescape(m.group(1))
    next_data = json.loads(payload_text)
    canonical = (json.dumps(next_data, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    raw_path = out / "raw" / f"fotmob-{pid}-next-data.json"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(canonical)

    root = get_data_root(next_data)
    all_birth = []
    data_birth = []
    id_markers = []
    for p, k, v in walk(next_data):
        if is_birth_key(k) and not isinstance(v, (dict, list)):
            all_birth.append({"path": p, "key": k, "value": v, "fullDate": valid_full_date(v)})
        nk = norm_key(k)
        if nk in {"id", "playerid", "fotmobplayerid"} and str(v) == str(pid):
            id_markers.append(p)
    if root is not None:
        for p, k, v in walk(root, "$.props.pageProps.data"):
            if is_birth_key(k) and not isinstance(v, (dict, list)):
                data_birth.append({"path": p, "key": k, "value": v, "fullDate": valid_full_date(v)})

    full = [x for x in data_birth if x.get("fullDate")]
    return {
        "fotmobPlayerId": pid,
        "label": spec["label"],
        "requestedUrl": url,
        "capturedAt": captured,
        "httpStatus": status,
        "response": {
            "htmlBytes": len(html),
            "htmlSha256": html_sha,
            "contentType": headers.get("Content-Type"),
        },
        "nextData": {
            "rawPath": str(raw_path.relative_to(out)),
            "bytes": len(canonical),
            "sha256": sha(canonical),
            "buildId": next_data.get("buildId"),
            "page": next_data.get("page"),
            "dataRootPresent": root is not None,
        },
        "identityBinding": {
            "requestedExactFotmobPlayerId": pid,
            "matchingIdPaths": sorted(id_markers),
            "exactIdObservedInNextData": bool(id_markers),
        },
        "birthCandidatesWithinDataRoot": data_birth,
        "birthCandidatesAnywhereInNextData": all_birth,
        "fullDateCandidatesWithinDataRoot": full,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)

    records = []
    technical = []
    for spec in PLAYERS:
        try:
            records.append(probe_player(spec, out))
        except Exception as e:
            technical.append({
                "fotmobPlayerId": spec["fotmobPlayerId"],
                "label": spec["label"],
                "errorType": type(e).__name__,
                "detail": str(e),
                "traceback": traceback.format_exc()[-8000:],
            })

    common_paths = None
    for r in records:
        paths = {x["path"] for x in r["fullDateCandidatesWithinDataRoot"]}
        common_paths = paths if common_paths is None else common_paths.intersection(paths)
    common_paths = sorted(common_paths or [])

    chosen_path = common_paths[0] if len(common_paths) == 1 else None
    chosen_values = []
    if chosen_path:
        for r in records:
            hit = [x for x in r["fullDateCandidatesWithinDataRoot"] if x["path"] == chosen_path]
            if len(hit) == 1:
                chosen_values.append({"fotmobPlayerId": r["fotmobPlayerId"], "dateOfBirth": hit[0]["fullDate"], "rawValue": hit[0]["value"]})

    ids_bound = len(records) == 4 and all(r["identityBinding"]["exactIdObservedInNextData"] for r in records)
    full_date_semantics = chosen_path is not None and len(chosen_values) == 4
    status = "PASS" if not technical and ids_bound and full_date_semantics else "INSUFFICIENT_EVIDENCE"

    result = {
        "schema": "NEXUS_D1_FOTMOB_DOB_SEMANTICS_PROBE_V1",
        "protocolVersion": "1.1",
        "status": status,
        "capturedAt": now(),
        "probeSubjects": [dict(x) for x in PLAYERS],
        "semantics": {
            "authoritySurface": "FotMob player page __NEXT_DATA__",
            "dataRoot": "$.props.pageProps.data",
            "dateOfBirthPath": chosen_path,
            "precision": "DAY" if full_date_semantics else None,
            "acceptedFormat": "YYYY-MM-DD or ISO datetime carrying an exact YYYY-MM-DD" if full_date_semantics else None,
            "ageOnlyAccepted": False,
            "yearOnlyAccepted": False,
            "identityBoundByExactFotmobPlayerId": ids_bound,
            "dobUsedForIdentitySelection": False,
            "commonFullDateCandidatePaths": common_paths,
            "values": chosen_values,
        },
        "summary": {
            "subjectsExpected": 4,
            "subjectsFetched": len(records),
            "technicalFailures": len(technical),
            "exactIdBindingPass": sum(1 for r in records if r["identityBinding"]["exactIdObservedInNextData"]),
            "subjectsWithFullDateCandidateInDataRoot": sum(1 for r in records if r["fullDateCandidatesWithinDataRoot"]),
            "singleCommonFullDatePath": chosen_path is not None,
        },
        "technicalFailures": technical,
        "records": records,
        "governance": {
            "identityResolverExecuted": False,
            "fuzzyMatchingUsed": False,
            "nameOnlyMatchingUsed": False,
            "dobUsedForIdentitySelection": False,
            "computedAgeDerived": False,
            "secondPassCasesMutated": False,
            "trainingPromotionGranted": False,
            "f1Started": False,
            "d2Started": False,
        },
    }
    rb = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (out / "RESULT.json").write_bytes(rb)

    files = []
    for p in sorted(x for x in out.rglob("*") if x.is_file() and x.name != "MANIFEST.json"):
        b = p.read_bytes()
        files.append({"path": str(p.relative_to(out)), "size": len(b), "sha256": sha(b)})
    digest = sha("\n".join(f"{x['path']}\t{x['size']}\t{x['sha256']}" for x in files).encode())
    manifest = {
        "schema": "NEXUS_D1_FOTMOB_DOB_SEMANTICS_PROBE_MANIFEST_V1",
        "generatedAt": now(),
        "status": status,
        "files": files,
        "fileCount": len(files),
        "canonicalContentSha256": digest,
        "governance": result["governance"],
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"status": status, "summary": result["summary"], "semantics": result["semantics"]}, ensure_ascii=False, indent=2))
    if technical:
        raise SystemExit(2)
    if status != "PASS":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
