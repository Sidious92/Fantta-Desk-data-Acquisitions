from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.8",
}


def probe_comunio():
    url = "https://stats.comunio.de/search.php"
    params = {"lang":"en","season":2026,"orderBy":"points","direc":"DESC","startLimit":0}
    r = requests.get(url, params=params, headers=HEADERS, timeout=30, allow_redirects=True)
    soup = BeautifulSoup(r.content, "lxml")
    hrefs = [a.get("href") for a in soup.find_all("a", href=True)]
    return {
        "status": r.status_code,
        "final_url": r.url,
        "content_type": r.headers.get("content-type"),
        "bytes": len(r.content),
        "title": soup.title.get_text(" ", strip=True) if soup.title else None,
        "href_count": len(hrefs),
        "href_sample": hrefs[:80],
        "profile_like_hrefs": [h for h in hrefs if h and ("profile" in h.lower() or "player" in h.lower())][:80],
        "text_preview": re.sub(r"\\s+", " ", soup.get_text(" ", strip=True))[:3000],
        "html_preview": r.text[:5000],
    }


def get_biwenger_catalog():
    url = "https://cf.biwenger.com/api/v2/competitions/la-liga/data"
    r = requests.get(url, params={"lang":"en","score":2}, headers=HEADERS, timeout=30)
    out = {"status":r.status_code,"final_url":r.url,"content_type":r.headers.get("content-type"),"bytes":len(r.content)}
    try:
        obj = r.json()
    except Exception:
        out["body_preview"] = r.text[:2000]
        return out, None
    players = ((obj.get("data") or {}).get("players") or {}) if isinstance(obj,dict) else {}
    if isinstance(players, dict):
        arr = [p for p in players.values() if isinstance(p,dict)]
    elif isinstance(players,list):
        arr = [p for p in players if isinstance(p,dict)]
    else:
        arr=[]
    out["players"] = len(arr)
    out["player_fields"] = sorted({k for p in arr[:50] for k in p.keys()})
    sample = next((p for p in arr if p.get("slug")), None)
    out["sample"] = {k: sample.get(k) for k in ["id","name","slug","teamID","points","pointsLastSeason"]} if sample else None
    return out, sample


def probe_biwenger_detail(sample):
    if not sample:
        return {"error":"NO_SAMPLE"}
    slug = sample["slug"]
    base = f"https://cf.biwenger.com/api/v2/players/la-liga/{slug}"
    referer_headers = dict(HEADERS)
    referer_headers.update({"Referer":"https://biwenger.as.com/players","Accept":"application/json, text/plain, */*"})
    plain_fields = "*,team,fitness,reports(points,home,events,status(status,statusText),match(*,round,home,away),star),prices,competition,seasons,news,threads"
    encoded_fields = "*%2Cteam%2Cfitness%2Creports(points%2Chome%2Cevents%2Cstatus(status%2CstatusText)%2Cmatch(*%2Cround%2Chome%2Caway)%2Cstar)%2Cprices%2Ccompetition%2Cseasons%2Cnews%2Cthreads"
    tests = []
    candidates = [
        ("plain_params", {"fields":plain_fields,"score":2,"lang":"en"}, None),
        ("encoded_params", {"fields":encoded_fields,"score":2,"lang":"en"}, None),
        ("literal_query", None, f"{base}?fields={encoded_fields}&score=2&lang=en"),
        ("minimal", {"score":2,"lang":"en"}, None),
    ]
    for name, params, literal in candidates:
        u = literal or base
        try:
            r = requests.get(u, params=params, headers=referer_headers, timeout=30, allow_redirects=True)
            rec = {"name":name,"status":r.status_code,"final_url":r.url,"content_type":r.headers.get("content-type"),"bytes":len(r.content),"body_preview":r.text[:1200]}
            try:
                obj=r.json()
                data=(obj.get("data") or {}) if isinstance(obj,dict) else None
                rec["top_keys"] = sorted(obj.keys()) if isinstance(obj,dict) else None
                rec["data_keys"] = sorted(data.keys()) if isinstance(data,dict) else None
            except Exception:
                pass
            tests.append(rec)
        except Exception as exc:
            tests.append({"name":name,"error":str(exc)})
    return {"sample_slug":slug,"tests":tests}


def main():
    c = probe_comunio()
    bcat, sample = get_biwenger_catalog()
    bdetail = probe_biwenger_detail(sample)
    print(json.dumps({"comunio":c,"biwenger_catalog":bcat,"biwenger_detail":bdetail}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
