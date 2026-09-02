#!/usr/bin/env python3
import csv
import hashlib
import json
import re
import time
import unicodedata
from collections import defaultdict
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SEASONS = [2022, 2023, 2024, 2025]
BASE = "https://www.transfermarkt.com/serie-a/transfers/wettbewerb/IT1/saison_id/{season}/leihe/1/intern/1/plus/"
OUT = Path("artifacts/serie-a-five-season-transfer-ledgers-v1")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    s = s.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def text(el):
    return " ".join(el.stripped_strings) if el else ""

def detect_direction(box_text: str, table_idx: int) -> str:
    low = box_text.lower()
    if "arrivals" in low or "arrivi" in low or "incomings" in low:
        return "IN"
    if "departures" in low or "cessioni" in low or "outgoings" in low:
        return "OUT"
    return "IN" if table_idx == 0 else "OUT"

def semantic_type(fee: str) -> str:
    x = (fee or "").lower()
    if "end of loan" in x or "loan end" in x or "return from loan" in x:
        return "LOAN_RETURN_OR_END_OF_LOAN"
    if "loan" in x:
        return "LOAN"
    if "free transfer" in x or "free agent" in x:
        return "FREE_AGENT_OR_END_OF_CONTRACT"
    if "released" in x or "contract termination" in x:
        return "CONTRACT_TERMINATION"
    return "PERMANENT_OR_OTHER_EXPLICIT"

def extract_team_name(box):
    h = box.find(["h2", "h3"])
    if h:
        a = h.find("a")
        cand = text(a or h)
        cand = re.sub(r"\s+Transfers.*$", "", cand, flags=re.I).strip()
        if cand:
            return cand
    club_link = box.find("a", href=re.compile(r"/startseite/verein/"))
    return text(club_link) if club_link else ""

def row_fields(tr):
    tds = tr.find_all("td")
    if not tds:
        return None
    player_link = tr.find("a", href=re.compile(r"/profil/spieler/"))
    if not player_link:
        player_link = tr.find("a", href=re.compile(r"/spieler/"))
    player = text(player_link)
    if not player:
        return None
    club_links = tr.find_all("a", href=re.compile(r"/startseite/verein/"))
    counterparty = text(club_links[-1]) if club_links else ""
    fee = ""
    for td in reversed(tds):
        tx = text(td)
        if tx:
            fee = tx
            break
    age = ""
    pos = ""
    raw_cells = [text(td) for td in tds]
    for c in raw_cells:
        if re.fullmatch(r"\d{1,2}", c):
            age = c
            break
    if len(raw_cells) >= 2:
        pos = raw_cells[1]
    return player, age, pos, counterparty, fee, " | ".join(raw_cells)

def parse_season(season: int):
    url = BASE.format(season=season)
    r = requests.get(url, headers=HEADERS, timeout=45)
    raw = r.content
    # Transfermarkt can answer 202 to automated clients while still returning the
    # requested document. Authority is therefore established structurally below,
    # not from HTTP=200 alone. Any non-200/202 response remains fail-closed.
    if r.status_code not in (200, 202):
        raise RuntimeError(f"season {season}: HTTP {r.status_code}")
    soup = BeautifulSoup(raw, "html.parser")
    rows = []
    clubs = []

    for box in soup.select("div.box"):
        tables = box.select("table.items")
        if not tables:
            continue
        team = extract_team_name(box)
        if not team:
            continue
        if not box.find("a", href=re.compile(r"/profil/spieler/|/spieler/")):
            continue
        if team not in clubs:
            clubs.append(team)
        for ti, table in enumerate(tables):
            prev = table.find_previous(["h2", "h3", "h4"])
            d = detect_direction(text(prev) if prev else "", ti)
            for tr in table.select("tbody tr"):
                rf = row_fields(tr)
                if not rf:
                    continue
                player, age, pos, cp, fee, raw_cells = rf
                origin = cp if d == "IN" else team
                dest = team if d == "IN" else cp
                rows.append({
                    "season": f"{season}/{str(season+1)[-2:]}",
                    "seasonId": season,
                    "team": team,
                    "direction": d,
                    "player": player,
                    "normalizedPlayer": norm(player),
                    "age": age,
                    "position": pos,
                    "counterparty": cp,
                    "originClub": origin,
                    "destinationClub": dest,
                    "normalizedOrigin": norm(origin),
                    "normalizedDestination": norm(dest),
                    "feeOrTypeRaw": fee,
                    "semanticType": semantic_type(fee),
                    "sourceUrl": url,
                    "rawCells": raw_cells,
                })

    seen = set()
    dedup = []
    for x in rows:
        key = (x["team"], x["direction"], x["player"], x["counterparty"], x["feeOrTypeRaw"], x["rawCells"])
        if key not in seen:
            seen.add(key)
            dedup.append(x)
    rows = dedup

    clubset = sorted(set(x["team"] for x in rows))
    if len(clubset) != 20:
        preview = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:600]
        raise RuntimeError(f"season {season}: HTTP {r.status_code}; expected 20 clubs, parsed {len(clubset)}: {clubset}; bodyPreview={preview!r}")
    if not any(x["direction"] == "IN" for x in rows) or not any(x["direction"] == "OUT" for x in rows):
        raise RuntimeError(f"season {season}: missing direction")

    current_norm_clubs = {norm(c): c for c in clubset}
    groups = defaultdict(lambda: {"IN": [], "OUT": []})
    for i, x in enumerate(rows):
        internal = x["normalizedOrigin"] in current_norm_clubs and x["normalizedDestination"] in current_norm_clubs
        if internal and x["normalizedOrigin"] and x["normalizedDestination"]:
            k = (x["normalizedPlayer"], x["normalizedOrigin"], x["normalizedDestination"])
            groups[k][x["direction"]].append((i, x))

    events = []
    used = set()
    paired = 0
    for _, g in groups.items():
        n = min(len(g["IN"]), len(g["OUT"]))
        for j in range(n):
            ii, a = g["IN"][j]
            oi, b = g["OUT"][j]
            used.update([ii, oi])
            paired += 1
            events.append({
                "season": a["season"], "player": a["player"],
                "originClub": a["originClub"], "destinationClub": a["destinationClub"],
                "semanticType": a["semanticType"] if a["semanticType"] == b["semanticType"] else "MULTI_SOURCE_EXPLICIT_MOVEMENT",
                "sourceFaces": 2, "sourceTeams": f"{a['team']} | {b['team']}",
                "feeOrTypeRaw": a["feeOrTypeRaw"] or b["feeOrTypeRaw"],
            })
    for i, x in enumerate(rows):
        if i in used:
            continue
        events.append({
            "season": x["season"], "player": x["player"],
            "originClub": x["originClub"], "destinationClub": x["destinationClub"],
            "semanticType": x["semanticType"], "sourceFaces": 1,
            "sourceTeams": x["team"], "feeOrTypeRaw": x["feeOrTypeRaw"],
        })

    sd = OUT / str(season)
    sd.mkdir(parents=True, exist_ok=True)
    team_path = sd / "team-side.csv"
    event_path = sd / "unique-events.csv"
    raw_path = sd / "source.html"
    raw_path.write_bytes(raw)
    team_fields = list(rows[0].keys())
    with team_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=team_fields); w.writeheader(); w.writerows(rows)
    ev_fields = list(events[0].keys())
    with event_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ev_fields); w.writeheader(); w.writerows(events)

    meta = {
        "season": f"{season}/{str(season+1)[-2:]}",
        "sourceUrl": url,
        "httpStatus": r.status_code,
        "sourceHtmlSha256": sha256_bytes(raw),
        "clubCount": len(clubset),
        "clubs": clubset,
        "teamSideRows": len(rows),
        "incomingRows": sum(x["direction"] == "IN" for x in rows),
        "outgoingRows": sum(x["direction"] == "OUT" for x in rows),
        "pairedInternalSerieAEvents": paired,
        "uniqueSemanticEvents": len(events),
        "formulaCheck": len(events) == len(rows) - paired,
        "teamSideSha256": sha256_bytes(team_path.read_bytes()),
        "uniqueEventsSha256": sha256_bytes(event_path.read_bytes()),
        "status": "PASS" if len(clubset) == 20 and len(events) == len(rows)-paired else "FAIL",
    }
    (sd / "manifest.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    metas = []
    for s in SEASONS:
        metas.append(parse_season(s))
        time.sleep(4)
    global_meta = {
        "schema": "SERIE_A_FIVE_SEASON_TRANSFERMARKT_ACQUISITION_V1",
        "status": "PASS" if all(m["status"] == "PASS" for m in metas) else "FAIL",
        "seasons": metas,
    }
    (OUT / "summary.json").write_text(json.dumps(global_meta, indent=2, ensure_ascii=False), encoding="utf-8")
    if global_meta["status"] != "PASS":
        raise SystemExit(2)
    print(json.dumps(global_meta, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
