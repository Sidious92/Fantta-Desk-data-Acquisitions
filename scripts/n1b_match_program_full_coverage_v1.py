#!/usr/bin/env python3
import concurrent.futures as cf
import hashlib
import io
import json
import os
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader

BASE_SDP = "https://api-sdp.legaseriea.it/v1/serie-a/football"
BASE_WEB = "https://www.legaseriea.it"
OUT = Path("artifacts/n1b-match-program-full-coverage-v1")
OUT.mkdir(parents=True, exist_ok=True)

SEASONS = {
    "2021-22": "serie-a::Football_Season::4c67f7c66d484e559a65857eb5a7cbeb",
    "2022-23": "serie-a::Football_Season::65f4d59dedbb43b68197b0ff0529fa21",
    "2023-24": "serie-a::Football_Season::104a84bc07f641e685f70a850c6399eb",
    "2024-25": "serie-a::Football_Season::1e32f55e98fc408a9d1fc27c0ba43243",
    "2025-26": "serie-a::Football_Season::5f0e080fc3a44073984b75b3a8e06a8a",
}

# These two exclusions are inherited from the normalized T0A population, not invented here.
EXCLUDED_MATCH_UUIDS = {
    "e8ced69e18f042309a25a44b4837effd": "2022-23 relegation playoff absent from normalized T0A",
    "6b8d65604bb549edb97a60ea1344292e": "2024-25 Atalanta-Roma absent from normalized T0A",
}
EXPECTED_TARGET_MATCHES = 1899
UA = "Mozilla/5.0 (compatible; FantaNexus-N1B/1.0; scientific coverage audit)"


def req(url, *, timeout=25, binary=False):
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"}, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(0.8 * (attempt + 1))
                last = f"HTTP_{r.status_code}"
                continue
            return r
        except Exception as e:
            last = f"{type(e).__name__}:{e}"
            time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(last or "request_failed")


def slugify(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


def norm(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = s.replace("’", "'").replace("`", "'")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def extract_program_url(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.stripped_strings).lower()
        href = a.get("href", "")
        score = 0
        if "match program" in text or "match programme" in text:
            score += 10
        if "matchprogram" in href.lower() or "match-program" in href.lower():
            score += 8
        if href.lower().endswith(".pdf") and "images.legaseriea.it" in href.lower():
            score += 2
        if score:
            candidates.append((score, urljoin(page_url, href)))
    if candidates:
        return sorted(candidates, reverse=True)[0][1]
    # Fallback for hydrated JSON / escaped HTML.
    raw = html.replace("\\/", "/")
    for m in re.finditer(r"https://images\.legaseriea\.it/[^\"'<> ]+\.pdf", raw, flags=re.I):
        u = m.group(0)
        lo = raw[max(0, m.start()-500):m.end()+200].lower()
        if "match program" in lo or "matchprogram" in lo:
            return u
    return None


def pdf_text_and_meta(pdf_bytes):
    out = {"pdf_pages": None, "pdf_text_chars": 0, "roster_marker": False, "explicit_print_ts": None, "pdf_parse_error": None}
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        out["pdf_pages"] = len(reader.pages)
        text = "\n".join((p.extract_text() or "") for p in reader.pages)
        out["pdf_text_chars"] = len(text)
        nt = norm(text)
        out["roster_marker"] = ("rosa delle squadre" in nt) or ("rose delle squadre" in nt)
        # Only accept a timestamp when an explicit print/stampa label is nearby.
        for pat in [
            r"(?i)(?:stampato|stampa|printed)[^\n]{0,80}?(\d{1,2}[/-]\d{1,2}[/-]\d{4})[^\n]{0,30}?(\d{1,2}:\d{2})",
            r"(?i)(\d{1,2}[/-]\d{1,2}[/-]\d{4})[^\n]{0,30}?(\d{1,2}:\d{2})[^\n]{0,80}?(?:stampato|stampa|printed)",
        ]:
            m = re.search(pat, text)
            if m:
                ds, ts = m.group(1), m.group(2)
                for fmt in ("%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M"):
                    try:
                        out["explicit_print_ts"] = datetime.strptime(ds + " " + ts, fmt).isoformat()
                        break
                    except ValueError:
                        pass
                if out["explicit_print_ts"]:
                    break
        return text, out
    except Exception as e:
        out["pdf_parse_error"] = f"{type(e).__name__}:{e}"
        return "", out


def extract_named(lineup):
    rows = []
    for side in ("home", "away"):
        team = lineup.get(side) or {}
        for bucket in ("fielded", "benched"):
            for p in team.get(bucket) or []:
                rows.append({
                    "side": side,
                    "team": team.get("shortName"),
                    "bucket": bucket,
                    "playerId": p.get("playerId"),
                    "providerId": p.get("providerId"),
                    "name": p.get("shortName") or " ".join(x for x in [p.get("mediaFirstName"), p.get("mediaLastName")] if x),
                    "first": p.get("mediaFirstName"),
                    "last": p.get("mediaLastName"),
                    "display": p.get("displayName"),
                    "shirt": p.get("shirtName"),
                })
    return rows


def name_in_pdf(p, pdf_norm):
    variants = []
    for v in (p.get("name"), " ".join(x for x in [p.get("first"), p.get("last")] if x), p.get("shirt")):
        nv = norm(v)
        if nv and len(nv) >= 4:
            variants.append(nv)
    for v in dict.fromkeys(variants):
        if v in pdf_norm:
            return True, v, "FULL_VARIANT"
    last = norm(p.get("last"))
    first = norm(p.get("first"))
    if last and len(last) >= 4 and last in pdf_norm:
        # Surname-only is diagnostic, not an automatic identity closure.
        return None, last, "SURNAME_ONLY"
    return False, None, "UNRESOLVED"


def acquire_match(season, season_id, m):
    match_uuid = m["matchId"].split("::")[-1]
    home = (m.get("home") or {}).get("shortName") or "home"
    away = (m.get("away") or {}).get("shortName") or "away"
    slug = f"{slugify(home)}-vs-{slugify(away)}"
    page_url = f"{BASE_WEB}/serie-a/match/{match_uuid}/{slug}/info"
    rec = {
        "season": season,
        "match_uuid": match_uuid,
        "match_id": m.get("matchId"),
        "provider_id": m.get("providerId"),
        "kickoff_utc": m.get("matchDateUtc"),
        "kickoff_local": m.get("matchDateLocal"),
        "home": home,
        "away": away,
        "round": ((m.get("matchSet") or {}).get("index")),
        "info_url": page_url,
        "info_http": None,
        "match_program_url": None,
        "program_http": None,
        "program_sha256": None,
        "pdf_pages": None,
        "pdf_text_chars": 0,
        "roster_marker": False,
        "explicit_print_ts": None,
        "print_pre_kickoff": None,
        "lineup_http": None,
        "named_count": None,
        "named_full_match": None,
        "named_surname_only": None,
        "named_unresolved": None,
        "error": None,
    }
    try:
        ir = req(page_url)
        rec["info_http"] = ir.status_code
        if ir.status_code == 200:
            rec["match_program_url"] = extract_program_url(ir.text, page_url)
        if not rec["match_program_url"]:
            return rec

        pr = req(rec["match_program_url"], timeout=35)
        rec["program_http"] = pr.status_code
        if pr.status_code != 200 or not pr.content.startswith(b"%PDF"):
            return rec
        rec["program_sha256"] = hashlib.sha256(pr.content).hexdigest()
        text, meta = pdf_text_and_meta(pr.content)
        rec.update(meta)
        if rec.get("explicit_print_ts") and rec.get("kickoff_local"):
            try:
                pt = datetime.fromisoformat(rec["explicit_print_ts"])
                ko = datetime.fromisoformat(rec["kickoff_local"])
                rec["print_pre_kickoff"] = pt < ko
            except Exception:
                rec["print_pre_kickoff"] = None

        lineup_url = f"{BASE_SDP}/seasons/{season_id}/matches/{m['matchId']}/lineups?locale=en-GB"
        lr = req(lineup_url)
        rec["lineup_http"] = lr.status_code
        if lr.status_code == 200 and text:
            payload = lr.json()
            lineup = payload.get("home") and payload or payload.get("lineup") or payload
            named = extract_named(lineup)
            rec["named_count"] = len(named)
            pdf_norm = norm(text)
            c = Counter()
            unresolved = []
            for p in named:
                hit, variant, method = name_in_pdf(p, pdf_norm)
                c[method] += 1
                if hit is False:
                    unresolved.append({"playerId": p.get("playerId"), "name": p.get("name"), "team": p.get("team")})
            rec["named_full_match"] = c["FULL_VARIANT"]
            rec["named_surname_only"] = c["SURNAME_ONLY"]
            rec["named_unresolved"] = c["UNRESOLVED"]
            if unresolved:
                rec["unresolved_named"] = unresolved
        return rec
    except Exception as e:
        rec["error"] = f"{type(e).__name__}:{e}"
        return rec


def main():
    all_targets = []
    source_counts = {}
    exclusions_seen = []
    for season, sid in SEASONS.items():
        url = f"{BASE_SDP}/seasons/{sid}/matches?locale=en-GB"
        r = req(url)
        r.raise_for_status()
        payload = r.json()
        matches = payload.get("matches") or []
        source_counts[season] = len(matches)
        for m in matches:
            uuid = m["matchId"].split("::")[-1]
            if uuid in EXCLUDED_MATCH_UUIDS:
                exclusions_seen.append({"season": season, "match_uuid": uuid, "reason": EXCLUDED_MATCH_UUIDS[uuid]})
                continue
            all_targets.append((season, sid, m))

    if len(all_targets) != EXPECTED_TARGET_MATCHES:
        raise RuntimeError(f"TARGET_POPULATION_MISMATCH expected={EXPECTED_TARGET_MATCHES} observed={len(all_targets)} source_counts={source_counts} exclusions={exclusions_seen}")

    records = []
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        futs = [ex.submit(acquire_match, *x) for x in all_targets]
        for i, fut in enumerate(cf.as_completed(futs), 1):
            rec = fut.result()
            records.append(rec)
            if i % 100 == 0:
                print(f"completed {i}/{len(futs)}")

    records.sort(key=lambda x: (x["season"], x.get("kickoff_utc") or "", x["match_uuid"]))
    with (OUT / "match-audit.ndjson").open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    per = {}
    for season in SEASONS:
        rs = [r for r in records if r["season"] == season]
        per[season] = {
            "target_matches": len(rs),
            "info_200": sum(r["info_http"] == 200 for r in rs),
            "program_link_found": sum(bool(r["match_program_url"]) for r in rs),
            "program_pdf_200": sum(r["program_http"] == 200 and bool(r["program_sha256"]) for r in rs),
            "roster_marker_found": sum(bool(r["roster_marker"]) for r in rs),
            "explicit_print_timestamp": sum(bool(r["explicit_print_ts"]) for r in rs),
            "print_pre_kickoff_true": sum(r["print_pre_kickoff"] is True for r in rs),
            "print_pre_kickoff_false": sum(r["print_pre_kickoff"] is False for r in rs),
            "lineup_200": sum(r["lineup_http"] == 200 for r in rs),
            "named_count_total": sum((r["named_count"] or 0) for r in rs),
            "named_full_match_total": sum((r["named_full_match"] or 0) for r in rs),
            "named_surname_only_total": sum((r["named_surname_only"] or 0) for r in rs),
            "named_unresolved_total": sum((r["named_unresolved"] or 0) for r in rs),
            "request_errors": sum(bool(r["error"]) for r in rs),
        }
    overall = {
        "schema": "NEXUS_N1B_MATCH_PROGRAM_FULL_COVERAGE_AUDIT_V1",
        "status": "DIAGNOSTIC_ONLY_NO_TRAINING_MATERIALIZATION",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": "Lega Serie A official SDP + official legaseriea.it match info + official Match Program PDFs",
        "target_contract": {
            "population": "normalized T0A match population only",
            "expected_matches": EXPECTED_TARGET_MATCHES,
            "source_match_counts": source_counts,
            "explicit_exclusions": exclusions_seen,
        },
        "per_season": per,
    }
    overall["overall"] = {k: sum(v.get(k, 0) for v in per.values()) for k in [
        "target_matches", "info_200", "program_link_found", "program_pdf_200", "roster_marker_found",
        "explicit_print_timestamp", "print_pre_kickoff_true", "print_pre_kickoff_false", "lineup_200",
        "named_count_total", "named_full_match_total", "named_surname_only_total", "named_unresolved_total", "request_errors"
    ]}
    n = overall["overall"]["named_count_total"]
    overall["overall"]["named_full_match_rate"] = (overall["overall"]["named_full_match_total"] / n) if n else None
    with (OUT / "summary.json").open("w", encoding="utf-8") as f:
        json.dump(overall, f, ensure_ascii=False, indent=2, sort_keys=True)
    print(json.dumps(overall, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
