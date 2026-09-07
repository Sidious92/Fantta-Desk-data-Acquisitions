#!/usr/bin/env python3
import concurrent.futures as cf
import json
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_SDP = "https://api-sdp.legaseriea.it/v1/serie-a/football"
BASE_WEB = "https://www.legaseriea.it"
OUT = Path("artifacts/n1b-match-program-link-census-v1")
OUT.mkdir(parents=True, exist_ok=True)
SEASONS = {
    "2021-22": "serie-a::Football_Season::4c67f7c66d484e559a65857eb5a7cbeb",
    "2022-23": "serie-a::Football_Season::65f4d59dedbb43b68197b0ff0529fa21",
    "2023-24": "serie-a::Football_Season::104a84bc07f641e685f70a850c6399eb",
    "2024-25": "serie-a::Football_Season::1e32f55e98fc408a9d1fc27c0ba43243",
    "2025-26": "serie-a::Football_Season::5f0e080fc3a44073984b75b3a8e06a8a",
}
EXCLUDE = {
    "e8ced69e18f042309a25a44b4837effd",
    "6b8d65604bb549edb97a60ea1344292e",
}
UA = "Mozilla/5.0 (compatible; FantaNexus-N1B-Link-Census/1.0)"

def get(url, timeout=8):
    for i in range(2):
        try:
            return requests.get(url, headers={"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"}, timeout=timeout)
        except Exception:
            if i == 1:
                raise
            time.sleep(.2)

def slugify(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")

def find_program(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    best = []
    for a in soup.find_all("a", href=True):
        text = " ".join(a.stripped_strings).lower()
        href = a["href"]
        score = 0
        if "match program" in text or "match programme" in text: score += 10
        if "matchprogram" in href.lower() or "match-program" in href.lower(): score += 8
        if href.lower().endswith(".pdf") and "images.legaseriea.it" in href.lower(): score += 2
        if score: best.append((score, urljoin(page_url, href)))
    if best: return sorted(best, reverse=True)[0][1]
    raw = html.replace("\\/", "/")
    for m in re.finditer(r"https://images\.legaseriea\.it/[^\"'<> ]+\.pdf", raw, re.I):
        near = raw[max(0,m.start()-500):m.end()+200].lower()
        if "match program" in near or "matchprogram" in near: return m.group(0)
    return None

def check(t):
    season, sid, m = t
    uuid = m["matchId"].split("::")[-1]
    h=(m.get("home") or {}).get("shortName") or "home"
    a=(m.get("away") or {}).get("shortName") or "away"
    url=f"{BASE_WEB}/serie-a/match/{uuid}/{slugify(h)}-vs-{slugify(a)}/info"
    out={"season":season,"match_uuid":uuid,"kickoff":m.get("matchDateUtc"),"home":h,"away":a,"info_url":url,"info_http":None,"program_url":None,"error":None}
    try:
        r=get(url)
        out["info_http"]=r.status_code
        if r.status_code==200: out["program_url"]=find_program(r.text,url)
    except Exception as e:
        out["error"]=f"{type(e).__name__}:{e}"
    return out

def main():
    targets=[]; source_counts={}
    for season,sid in SEASONS.items():
        r=get(f"{BASE_SDP}/seasons/{sid}/matches?locale=en-GB", timeout=12); r.raise_for_status()
        ms=r.json().get("matches") or []; source_counts[season]=len(ms)
        for m in ms:
            if m["matchId"].split("::")[-1] not in EXCLUDE: targets.append((season,sid,m))
    assert len(targets)==1899,(len(targets),source_counts)
    rows=[]
    with cf.ThreadPoolExecutor(max_workers=40) as ex:
        for i,r in enumerate(ex.map(check,targets),1):
            rows.append(r)
            if i%200==0: print(i,flush=True)
    rows.sort(key=lambda r:(r["season"],r["kickoff"] or "",r["match_uuid"]))
    with (OUT/"census.ndjson").open("w",encoding="utf-8") as f:
        for r in rows:f.write(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n")
    per={}
    for s in SEASONS:
        rs=[r for r in rows if r["season"]==s]
        per[s]={
            "target":len(rs),
            "info_200":sum(r["info_http"]==200 for r in rs),
            "program_link":sum(bool(r["program_url"]) for r in rs),
            "errors":sum(bool(r["error"]) for r in rs),
            "http_statuses":dict(Counter(str(r["info_http"]) for r in rs)),
        }
    summary={"schema":"NEXUS_N1B_MATCH_PROGRAM_LINK_CENSUS_V1","created_at":datetime.now(timezone.utc).isoformat(),"target":1899,"source_counts":source_counts,"per_season":per}
    summary["overall"]={"target":sum(x["target"] for x in per.values()),"info_200":sum(x["info_200"] for x in per.values()),"program_link":sum(x["program_link"] for x in per.values()),"errors":sum(x["errors"] for x in per.values())}
    (OUT/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
if __name__=="__main__":main()
