from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

HEADERS={
    "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "Accept-Language":"en-US,en;q=0.8",
}


def table_summaries(soup):
    out=[]
    for i,t in enumerate(soup.find_all("table")[:8]):
        heads=[re.sub(r"\s+"," ",x.get_text(" ",strip=True)) for x in t.find_all(["th","td"])[:20]]
        out.append({"index":i,"rows":len(t.find_all("tr")),"cells_sample":heads})
    return out


def comunio_probe():
    base="https://stats.comunio.de"
    results=[]
    for season in [2026,2025,2024,2023,2022]:
        params={"name":"","minValue":"","maxValue":"","minPts":"","maxPts":"","startGd":1,"endGd":34,"season":season}
        r=requests.get(base+"/search",params=params,headers=HEADERS,timeout=30)
        s=BeautifulSoup(r.content,"lxml")
        hrefs=[a.get("href") for a in s.find_all("a",href=True) if "/csprofile/" in (a.get("href") or "")]
        rec={"season":season,"status":r.status_code,"url":r.url,"bytes":len(r.content),"profile_count":len(hrefs),"profile_sample":hrefs[:5],"tables":table_summaries(s)}
        if hrefs:
            href=hrefs[0]
            tests=[]
            for name,u,par in [
                ("plain",urljoin(base,href),None),
                ("season_query",urljoin(base,href),{"season":season}),
            ]:
                rr=requests.get(u,params=par,headers=HEADERS,timeout=30,allow_redirects=True)
                ss=BeautifulSoup(rr.content,"lxml")
                tests.append({
                    "name":name,"status":rr.status_code,"url":rr.url,"bytes":len(rr.content),
                    "title":ss.title.get_text(" ",strip=True) if ss.title else None,
                    "text_preview":re.sub(r"\s+"," ",ss.get_text(" ",strip=True))[:1600],
                    "tables":table_summaries(ss),
                })
            rec["profile_tests"]=tests
        results.append(rec)
    return results


def biwenger_probe():
    cat_url="https://cf.biwenger.com/api/v2/competitions/la-liga/data"
    r=requests.get(cat_url,params={"lang":"en","score":2},headers=HEADERS,timeout=30)
    obj=r.json(); players=((obj.get("data") or {}).get("players") or {})
    arr=list(players.values()) if isinstance(players,dict) else players
    sample=next(p for p in arr if isinstance(p,dict) and p.get("slug"))
    slug=sample["slug"]
    url=f"https://cf.biwenger.com/api/v2/players/la-liga/{slug}"
    fields="*,team,reports,seasons,prices,fitness,competition"
    rr=requests.get(url,params={"lang":"en","score":2,"fields":fields},headers={**HEADERS,"Referer":"https://biwenger.as.com/players"},timeout=30)
    data=(rr.json().get("data") or {})
    seasons=data.get("seasons") or []
    out={
        "sample":{"id":sample.get("id"),"name":sample.get("name"),"slug":slug},
        "detail_status":rr.status_code,"detail_url":rr.url,"data_keys":sorted(data.keys()),
        "seasons_count":len(seasons),"seasons_sample":seasons[:6],
        "reports_count":len(data.get("reports") or []),"prices_count":len(data.get("prices") or []),
    }
    tests=[]
    for season in seasons[:4]:
        for key in ["id","slug"]:
            value=season.get(key) if isinstance(season,dict) else None
            if value is None: continue
            tr=requests.get(url,params={"lang":"en","score":2,"fields":fields,"season":value},headers={**HEADERS,"Referer":"https://biwenger.as.com/players"},timeout=30)
            try: td=(tr.json().get("data") or {})
            except Exception: td={}
            tests.append({"season_key":key,"season_value":value,"status":tr.status_code,"url":tr.url,"data_keys":sorted(td.keys()) if isinstance(td,dict) else [],"reports_count":len(td.get("reports") or []) if isinstance(td,dict) else None,"seasons_count":len(td.get("seasons") or []) if isinstance(td,dict) else None})
    out["season_param_tests"]=tests
    return out


def main():
    print(json.dumps({"comunio":comunio_probe(),"biwenger":biwenger_probe()},ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
