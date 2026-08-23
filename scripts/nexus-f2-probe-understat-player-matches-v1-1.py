#!/usr/bin/env python3
import codecs
import csv
import hashlib
import io
import json
import re
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "NEXUS_F2_UNDERSTAT_PLAYER_MATCH_TEMPORAL_PROBE_V1_1"
OUT = Path(".nexus-f2-understat-player-match-temporal-probe-v1-1")
RAW = OUT / "raw"
UNDERSTAT_COMMIT = "768b7ca0b977a5e6b4b429c7b0cf750e8269f2fc"
UNDERSTAT_SHA256 = "b78fad5f01844a0fdab0d89474dafba9b86c586d2f0ce88f0ce2c9af70d2bc64"
CSV_URL = f"https://raw.githubusercontent.com/vibedatascience/understat_players_aggregated/{UNDERSTAT_COMMIT}/understat_players_aggregated_2014_2024.csv"
PLAYER_URL = "https://understat.com/player/{player_id}"
UA = "Mozilla/5.0 (compatible; FantaNexus-F2-Temporal-Probe/1.1)"

COHORT = [
    {"playerId": "1305", "name": "Lukasz Skorupski", "classicRole": "P"},
    {"playerId": "1093", "name": "Mattia Perin", "classicRole": "P"},
    {"playerId": "1541", "name": "Stefan de Vrij", "classicRole": "D"},
    {"playerId": "1463", "name": "Francesco Acerbi", "classicRole": "D"},
    {"playerId": "1471", "name": "Lorenzo Pellegrini", "classicRole": "C"},
    {"playerId": "1122", "name": "Manuel Locatelli", "classicRole": "C"},
    {"playerId": "1294", "name": "Paulo Dybala", "classicRole": "A"},
    {"playerId": "1612", "name": "Domenico Berardi", "classicRole": "A"}
]
OBSERVED = ["games", "time", "goals", "npg", "assists", "shots", "key_passes"]
EXPECTED_MODEL_FIELDS = ["xG", "npxG", "xA", "xGChain", "xGBuildup"]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/json,*/*"})
    with urllib.request.urlopen(req, timeout=90) as r:
        if r.status != 200:
            raise RuntimeError(f"HTTP_{r.status}:{url}")
        return r.read()


def season_label(value) -> str:
    text = str(value or "").strip()
    m = re.fullmatch(r"(\d{4})/(\d{2})", text)
    if m:
        y = int(m.group(1))
        expected = (y + 1) % 100
        if int(m.group(2)) != expected:
            raise ValueError(f"invalid season label {text!r}")
        return text
    if re.fullmatch(r"\d{4}", text):
        y = int(text)
        return f"{y}/{(y + 1) % 100:02d}"
    raise ValueError(f"unsupported season format {text!r}")


def parse_matches(html: str):
    m = re.search(r"(?:var\s+)?matchesData\s*=\s*JSON\.parse\('(.+?)'\);", html, flags=re.DOTALL)
    if not m:
        raise RuntimeError("MATCHES_DATA_PAYLOAD_NOT_FOUND")
    encoded = m.group(1)
    try:
        decoded = codecs.escape_decode(encoded.encode("utf-8"))[0].decode("utf-8")
    except Exception:
        decoded = bytes(encoded, "utf-8").decode("unicode_escape")
    payload = json.loads(decoded)
    matches = payload.get("matches") if isinstance(payload, dict) else payload
    if not isinstance(matches, list):
        raise RuntimeError("MATCHES_DATA_SHAPE_INVALID")
    return matches


def integer(value, field, pid, season):
    try:
        f = float(value)
        i = int(f)
        if f != i:
            raise ValueError
        return i
    except Exception as exc:
        raise RuntimeError(f"NON_INTEGER_{field}:{pid}:{season}:{value!r}") from exc


def reconstruct(rows, pid, season):
    out = {k: 0 for k in OBSERVED}
    out["games"] = len(rows)
    dates, match_ids = [], set()
    for r in rows:
        d = str(r.get("date") or "").split()[0]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
            raise RuntimeError(f"INVALID_DATE:{pid}:{season}:{r.get('id')}:{r.get('date')!r}")
        datetime.strptime(d, "%Y-%m-%d")
        dates.append(d)
        mid = str(r.get("id") or "")
        if not mid or mid in match_ids:
            raise RuntimeError(f"INVALID_MATCH_ID:{pid}:{season}:{mid!r}")
        match_ids.add(mid)
        for field in ["time", "goals", "npg", "assists", "shots", "key_passes"]:
            out[field] += integer(r.get(field, 0), field, pid, season)
    out["firstMatchDate"] = min(dates)
    out["lastMatchDate"] = max(dates)
    out["matchIdsSha256"] = sha256("\n".join(sorted(match_ids)).encode())
    return out


def write_json(path: Path, obj):
    raw = (json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"path": str(path.relative_to(OUT)), "bytes": len(raw), "sha256": sha256(raw)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    csv_raw = fetch(CSV_URL)
    if sha256(csv_raw) != UNDERSTAT_SHA256:
        raise RuntimeError("PINNED_CSV_SHA256_MISMATCH")

    cohort_ids = {x["playerId"] for x in COHORT}
    source = defaultdict(list)
    reader = csv.DictReader(io.StringIO(csv_raw.decode("utf-8-sig")))
    for row in reader:
        pid = str(row.get("id") or "")
        if pid in cohort_ids and row.get("league") == "Serie_A":
            source[(pid, season_label(row.get("season")))].append(row)

    failures, comparisons, player_evidence = [], [], []
    total_match_rows = 0
    dated_rows = 0

    for n, subject in enumerate(COHORT):
        pid = subject["playerId"]
        if n:
            time.sleep(1.0)
        html_raw = fetch(PLAYER_URL.format(player_id=pid))
        html_sha = sha256(html_raw)
        (RAW / f"player-{pid}.html").write_bytes(html_raw)
        matches = parse_matches(html_raw.decode("utf-8", errors="replace"))
        matches_raw = (json.dumps(matches, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        (RAW / f"player-{pid}-matches.json").write_bytes(matches_raw)
        total_match_rows += len(matches)
        dated_rows += sum(bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(r.get("date") or "").split()[0])) for r in matches)

        by_season = defaultdict(list)
        for r in matches:
            try:
                by_season[season_label(r.get("season"))].append(r)
            except Exception:
                failures.append({"code": "MATCH_SEASON_INVALID", "playerId": pid, "matchId": r.get("id"), "season": r.get("season")})

        src_seasons = sorted((s, rows) for (p, s), rows in source.items() if p == pid)
        player_evidence.append({
            **subject,
            "htmlBytes": len(html_raw),
            "htmlSha256": html_sha,
            "matchRows": len(matches),
            "matchesPayloadSha256": sha256(matches_raw),
            "pinnedSerieASeasonRows": len(src_seasons)
        })

        for season, rows in src_seasons:
            if len(rows) != 1:
                failures.append({"code": "SOURCE_DUPLICATE_PLAYER_LEAGUE_SEASON", "playerId": pid, "season": season, "rows": len(rows)})
                continue
            match_rows = by_season.get(season, [])
            if not match_rows:
                failures.append({"code": "MATCH_RECONSTRUCTION_MISSING", "playerId": pid, "season": season})
                continue
            recon = reconstruct(match_rows, pid, season)
            src = rows[0]
            fields = {}
            exact = True
            for field in OBSERVED:
                a = integer(src.get(field), field, pid, season)
                b = recon[field]
                equal = a == b
                fields[field] = {"sourceAggregate": a, "matchReconstruction": b, "equal": equal}
                exact = exact and equal
            row = {
                "playerId": pid,
                "playerName": subject["name"],
                "classicRole": subject["classicRole"],
                "season": season,
                "sourceTeamTitle": src.get("team_title"),
                "sourceMultiClub": "," in str(src.get("team_title") or ""),
                "firstMatchDate": recon["firstMatchDate"],
                "lastMatchDate": recon["lastMatchDate"],
                "matchCount": recon["games"],
                "fieldResults": fields,
                "allObservedFieldsExact": exact
            }
            comparisons.append(row)
            if not exact:
                failures.append({"code": "OBSERVED_RECONCILIATION_MISMATCH", "playerId": pid, "season": season, "fieldResults": fields})

    role_counts = defaultdict(int)
    for x in COHORT:
        role_counts[x["classicRole"]] += 1
    exact_comparisons = sum(x["allObservedFieldsExact"] for x in comparisons)
    status = "PASS" if comparisons and not failures and exact_comparisons == len(comparisons) and dated_rows == total_match_rows else "FAIL"
    report = {
        "schema": SCHEMA,
        "status": status,
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "supersedesFailedProbe": "NEXUS_F2_UNDERSTAT_PLAYER_MATCH_TEMPORAL_PROBE_V1",
        "correction": "Normalize pinned source season values already encoded as YYYY/YY as well as match payload YYYY values.",
        "source": {
            "provider": "UNDERSTAT",
            "pinnedAggregateCommit": UNDERSTAT_COMMIT,
            "pinnedAggregateSha256": UNDERSTAT_SHA256,
            "playerEndpoint": "https://understat.com/player/{player_id}"
        },
        "cohort": {
            "players": len(COHORT),
            "selection": "DETERMINISTIC_EXACT_F1_D1_BOUND_LONG_HISTORY_TWO_PER_CLASSIC_ROLE",
            "roleCounts": dict(sorted(role_counts.items()))
        },
        "matchShape": {
            "totalRows": total_match_rows,
            "datedRows": dated_rows,
            "allRowsDated": total_match_rows > 0 and dated_rows == total_match_rows
        },
        "reconciliation": {
            "comparisons": len(comparisons),
            "exactComparisons": exact_comparisons,
            "allComparedSeasonsExact": len(comparisons) > 0 and exact_comparisons == len(comparisons),
            "fields": OBSERVED,
            "rows": comparisons
        },
        "temporalDecision": {
            "observedEventStableFields": "PROBE_SUPPORTS_FULL_RECONSTRUCTION_ONLY_IF_STATUS_PASS",
            "expectedModelFields": EXPECTED_MODEL_FIELDS,
            "expectedModelFieldsReleased": False,
            "expectedMetricReason": "Historical match dates do not establish expected-metric vintage or invariance."
        },
        "playerEvidence": player_evidence,
        "failures": failures,
        "governance": {
            "newProviderIntroduced": False,
            "fuzzyMatchingUsed": False,
            "f2ParametersFitted": False,
            "expectedMetricsPromoted": False,
            "canonicalPredictiveEngineModified": False
        }
    }
    probe_meta = write_json(OUT / "PROBE.json", report)
    raw_meta = []
    for p in sorted(RAW.iterdir()):
        if p.is_file():
            raw_meta.append({"path": str(p.relative_to(OUT)), "bytes": p.stat().st_size, "sha256": sha256(p.read_bytes())})
    manifest = {
        "schema": "NEXUS_F2_UNDERSTAT_PLAYER_MATCH_TEMPORAL_PROBE_MANIFEST_V1_1",
        "status": status,
        "probe": probe_meta,
        "rawFiles": raw_meta
    }
    manifest_meta = write_json(OUT / "MANIFEST.json", manifest)
    print(json.dumps({
        "status": status,
        "players": len(COHORT),
        "matchRows": total_match_rows,
        "comparisons": len(comparisons),
        "exactComparisons": exact_comparisons,
        "failureCount": len(failures),
        "probeSha256": probe_meta["sha256"],
        "manifestSha256": manifest_meta["sha256"]
    }, indent=2))
    if status != "PASS":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
