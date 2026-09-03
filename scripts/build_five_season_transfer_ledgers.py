from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

YEARS = [2022, 2023, 2024, 2025]
OUT = Path("artifacts/five-season-transfer-ledgers")
OUT.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def club_id_from_href(href: str | None) -> str | None:
    if not href:
        return None
    m = re.search(r"/(?:startseite|transfers)/verein/(\d+)", href)
    if not m:
        m = re.search(r"/verein/(\d+)", href)
    return m.group(1) if m else None


def player_id_from_href(href: str | None) -> str | None:
    if not href:
        return None
    m = re.search(r"/spieler/(\d+)", href)
    return m.group(1) if m else None


def classify(fee: str, counter: str) -> str:
    x = f"{fee} {counter}".lower()
    if "end of loan" in x:
        return "LOAN_RETURN_OR_END_OF_LOAN"
    if "loan" in x:
        return "LOAN"
    if "without club" in x or "free agent" in x:
        return "FREE_AGENT_OR_END_OF_CONTRACT"
    if "retired" in x or "retirement" in x:
        return "RETIREMENT"
    if "contract termination" in x:
        return "CONTRACT_TERMINATION"
    if "free transfer" in x:
        return "FREE_TRANSFER"
    return "PERMANENT_OR_OTHER_EXPLICIT"


def parse_expected(html: str) -> tuple[int | None, int | None]:
    soup = BeautifulSoup(html, "html.parser")
    text = norm(soup.get_text(" ", strip=True))
    ma = re.search(r"Arrivals:\s*([\d,.]+)", text, re.I)
    md = re.search(r"Departures:\s*([\d,.]+)", text, re.I)
    def n(m):
        return int(re.sub(r"\D", "", m.group(1))) if m else None
    return n(ma), n(md)


def fetch_expanded(year: int) -> tuple[str, str]:
    urls = [
        f"https://www.transfermarkt.com/serie-a/transfers/wettbewerb/IT1/saison_id/{year}/leihe/1/intern/1/plus/",
        f"https://www.transfermarkt.com/serie-a/transfers/wettbewerb/IT1/saison_id/{year}/intern/1/leihe/1/plus/",
    ]
    last = None
    for u in urls:
        r = requests.get(u, headers=HEADERS, timeout=45)
        last = (u, r)
        if r.status_code == 200 and "Transfers" in r.text and "Transfer record" in r.text:
            return u, r.text
    u, r = last
    raise RuntimeError(f"Transfermarkt fetch failed year={year} status={r.status_code} url={u}")


def parse_expanded(year: int, html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    faces: list[dict[str, Any]] = []
    for box in soup.select("div.box"):
        headline = box.select_one("h2.content-box-headline")
        if not headline:
            continue
        club_link = None
        for a in headline.find_all("a", href=True):
            if club_id_from_href(a.get("href")):
                club_link = a
                break
        if not club_link:
            continue
        club_name = norm(club_link.get("title") or club_link.get_text(" ", strip=True))
        current_club_id = club_id_from_href(club_link.get("href"))
        if not current_club_id:
            continue

        for table in box.select("table.items"):
            th0 = table.select_one("thead th")
            direction = norm(th0.get_text(" ", strip=True)).lower() if th0 else ""
            if direction not in {"in", "out"}:
                # Transfermarkt sometimes puts the header text in a colspan row.
                hdr = norm(table.get_text(" ", strip=True)[:40]).lower()
                if hdr.startswith("in "):
                    direction = "in"
                elif hdr.startswith("out "):
                    direction = "out"
                else:
                    continue

            for tr in table.select("tbody tr"):
                tds = tr.find_all("td", recursive=False)
                if len(tds) < 7:
                    continue
                p_link = None
                for a in tds[0].find_all("a", href=True):
                    if player_id_from_href(a.get("href")):
                        p_link = a
                        break
                if not p_link:
                    continue
                player_id = player_id_from_href(p_link.get("href"))
                player_name = norm(p_link.get("title") or p_link.get_text(" ", strip=True))

                # Counterparty club is normally in the penultimate cell.
                counter_td = tds[-2]
                counter_link = None
                for a in counter_td.find_all("a", href=True):
                    if club_id_from_href(a.get("href")):
                        counter_link = a
                        break
                counter_name = norm(counter_link.get("title") or counter_link.get_text(" ", strip=True)) if counter_link else norm(counter_td.get_text(" ", strip=True))
                counter_id = club_id_from_href(counter_link.get("href")) if counter_link else None
                fee_text = norm(tds[-1].get_text(" ", strip=True))
                semantic = classify(fee_text, counter_name)

                if direction == "in":
                    from_id, from_name = counter_id, counter_name
                    to_id, to_name = current_club_id, club_name
                else:
                    from_id, from_name = current_club_id, club_name
                    to_id, to_name = counter_id, counter_name

                faces.append({
                    "season": f"{year}/{str(year+1)[-2:]}",
                    "season_start": year,
                    "movement": direction.upper(),
                    "player_id": player_id,
                    "player_name": player_name,
                    "current_club_id": current_club_id,
                    "current_club": club_name,
                    "from_club_id": from_id or "",
                    "from_club": from_name,
                    "to_club_id": to_id or "",
                    "to_club": to_name,
                    "semantic_type": semantic,
                    "fee_text": fee_text,
                    "source": "TRANSFERMARKT_EXPANDED",
                })
    return faces


def load_backbone(year: int) -> list[dict[str, str]]:
    url = f"https://raw.githubusercontent.com/eordo/transfermarkt-data/master/serie_a/{year}.csv"
    r = requests.get(url, timeout=45)
    r.raise_for_status()
    p = OUT / f"serie-a-{year}-structured-backbone.csv"
    p.write_bytes(r.content)
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def dedup_faces(faces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # We only collapse directionally compatible IN/OUT faces. Multiple occurrences
    # of the same base key are retained using max(IN_count, OUT_count), protecting
    # repeated/multi-hop activity from accidental collapse.
    groups: dict[tuple, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: {"IN": [], "OUT": []})
    for f in faces:
        key = (
            f["season_start"], f["player_id"], f["from_club_id"], f["from_club"].casefold(),
            f["to_club_id"], f["to_club"].casefold(), f["semantic_type"], f["fee_text"].casefold(),
        )
        groups[key][f["movement"]].append(f)

    events: list[dict[str, Any]] = []
    eid = 0
    for key in sorted(groups, key=lambda x: tuple(str(v) for v in x)):
        ins, outs = groups[key]["IN"], groups[key]["OUT"]
        n = max(len(ins), len(outs))
        for i in range(n):
            a = ins[i] if i < len(ins) else None
            b = outs[i] if i < len(outs) else None
            src = a or b
            eid += 1
            events.append({
                "event_id": f"TM-{src['season_start']}-{eid:05d}",
                "season": src["season"],
                "player_id": src["player_id"],
                "player_name": src["player_name"],
                "from_club_id": src["from_club_id"],
                "from_club": src["from_club"],
                "to_club_id": src["to_club_id"],
                "to_club": src["to_club"],
                "semantic_type": src["semantic_type"],
                "fee_text": src["fee_text"],
                "paired_internal_faces": int(a is not None and b is not None),
                "source_faces": ("IN+OUT" if a is not None and b is not None else ("IN" if a is not None else "OUT")),
            })
    return events


def write_csv(path: Path, rows: list[dict[str, Any]]):
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)


def main():
    global_manifest = {"schema": "NEXUS_FIVE_SEASON_TRANSFER_LEDGER_RUN_V1", "seasons": []}
    for year in YEARS:
        backbone = load_backbone(year)
        url, html = fetch_expanded(year)
        html_path = OUT / f"transfermarkt-serie-a-{year}-expanded.html"
        html_path.write_text(html, encoding="utf-8")
        expected_in, expected_out = parse_expected(html)
        faces = parse_expanded(year, html)
        actual_in = sum(1 for f in faces if f["movement"] == "IN")
        actual_out = sum(1 for f in faces if f["movement"] == "OUT")
        events = dedup_faces(faces)
        face_path = OUT / f"serie-a-{year}-team-side-expanded.csv"
        event_path = OUT / f"serie-a-{year}-unique-semantic-events.csv"
        write_csv(face_path, faces)
        write_csv(event_path, events)
        manifest = {
            "season": f"{year}/{str(year+1)[-2:]}",
            "source_url": url,
            "expected_transfermarkt_arrivals": expected_in,
            "expected_transfermarkt_departures": expected_out,
            "parsed_arrivals": actual_in,
            "parsed_departures": actual_out,
            "team_side_faces": len(faces),
            "unique_semantic_events": len(events),
            "paired_internal_events": sum(int(e["paired_internal_faces"]) for e in events),
            "structured_backbone_rows": len(backbone),
            "completeness_gate": "PASS" if expected_in == actual_in and expected_out == actual_out else "FAIL_CLOSED_COUNT_MISMATCH",
            "files": {
                "team_side": {"path": face_path.name, "sha256": sha256(face_path)},
                "unique_events": {"path": event_path.name, "sha256": sha256(event_path)},
                "structured_backbone": {"path": f"serie-a-{year}-structured-backbone.csv", "sha256": sha256(OUT / f"serie-a-{year}-structured-backbone.csv")},
                "raw_html": {"path": html_path.name, "sha256": sha256(html_path)},
            },
        }
        mp = OUT / f"serie-a-{year}-ledger-manifest.json"
        mp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        global_manifest["seasons"].append(manifest)

    gm = OUT / "five-season-ledger-run-manifest.json"
    gm.write_text(json.dumps(global_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if any(s["completeness_gate"] != "PASS" for s in global_manifest["seasons"]):
        raise SystemExit("FAIL_CLOSED: at least one Transfermarkt expanded count mismatch")

if __name__ == "__main__":
    main()
