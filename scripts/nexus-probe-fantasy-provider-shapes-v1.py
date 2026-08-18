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


def summarize_forms(soup):
    forms = []
    for idx, form in enumerate(soup.find_all("form")):
        fields = []
        for el in form.find_all(["input", "select", "button", "textarea"]):
            rec = {
                "tag": el.name,
                "name": el.get("name"),
                "type": el.get("type"),
                "value": el.get("value"),
            }
            if el.name == "select":
                rec["selected"] = [
                    {"value": o.get("value"), "text": o.get_text(" ", strip=True)}
                    for o in el.find_all("option") if o.has_attr("selected")
                ]
                rec["options_sample"] = [
                    {"value": o.get("value"), "text": o.get_text(" ", strip=True)}
                    for o in el.find_all("option")[:12]
                ]
            fields.append(rec)
        forms.append({
            "index": idx,
            "method": (form.get("method") or "GET").upper(),
            "action": form.get("action"),
            "id": form.get("id"),
            "class": form.get("class"),
            "text_preview": re.sub(r"\s+", " ", form.get_text(" ", strip=True))[:1000],
            "fields": fields,
        })
    return forms


def probe_comunio():
    url = "https://stats.comunio.de/search.php"
    base_params = {"lang":"en","season":2026,"orderBy":"points","direc":"DESC","startLimit":0}
    r = requests.get(url, params=base_params, headers=HEADERS, timeout=30, allow_redirects=True)
    soup = BeautifulSoup(r.content, "lxml")
    hrefs = [a.get("href") for a in soup.find_all("a", href=True)]
    forms = summarize_forms(soup)

    # Try to submit the player-search form using the actual names discovered
    # from the page. Blank-name searches are useful because the target is a
    # complete ranked player table, not a single player lookup.
    submit_tests = []
    candidate_form = None
    for f in forms:
        names = {x.get("name") for x in f["fields"] if x.get("name")}
        if "season" in names and ("name" in names or "playerName" in names or "search" in names):
            candidate_form = f
            break
    if candidate_form is None:
        for f in forms:
            if "Player Search" in f.get("text_preview", ""):
                candidate_form = f
                break

    if candidate_form:
        defaults = {}
        submit_names = []
        for field in candidate_form["fields"]:
            name = field.get("name")
            if not name:
                continue
            tag = field.get("tag")
            typ = (field.get("type") or "").lower()
            if tag == "select":
                selected = field.get("selected") or []
                if selected:
                    defaults[name] = selected[0].get("value")
                elif field.get("options_sample"):
                    defaults[name] = field["options_sample"][0].get("value")
            elif typ in {"submit", "button"}:
                submit_names.append((name, field.get("value") or "Search"))
            elif typ not in {"checkbox", "radio"}:
                defaults[name] = field.get("value") or ""
        defaults["season"] = "2026"
        for key in ["name", "playerName", "searchName"]:
            if key in defaults:
                defaults[key] = ""
        # Explicitly request broad ranges if the form exposes them.
        for key in ["minPoints", "minP", "pointsMin", "minValue", "mvMin"]:
            if key in defaults:
                defaults[key] = ""
        tests = [("defaults", dict(defaults))]
        for submit_name, submit_value in submit_names[:3]:
            p = dict(defaults)
            p[submit_name] = submit_value
            tests.append((f"submit_{submit_name}", p))
        # Common legacy submit conventions, harmless if ignored.
        for extra in [
            {"submit":"Search"}, {"search":"Search"}, {"doSearch":"1"}, {"send":"1"}
        ]:
            p = dict(defaults); p.update(extra)
            tests.append(("extra_" + next(iter(extra)), p))

        target = urljoin(r.url, candidate_form.get("action") or "")
        for name, payload in tests:
            try:
                if candidate_form.get("method") == "POST":
                    rr = requests.post(target, data=payload, headers=HEADERS, timeout=30, allow_redirects=True)
                else:
                    rr = requests.get(target, params=payload, headers=HEADERS, timeout=30, allow_redirects=True)
                ss = BeautifulSoup(rr.content, "lxml")
                hh = [a.get("href") for a in ss.find_all("a", href=True)]
                submit_tests.append({
                    "name": name,
                    "status": rr.status_code,
                    "final_url": rr.url,
                    "bytes": len(rr.content),
                    "title": ss.title.get_text(" ", strip=True) if ss.title else None,
                    "profile_hrefs": [h for h in hh if h and ("profile" in h.lower() or "spieler" in h.lower())][:40],
                    "row_count": len(ss.find_all("tr")),
                    "text_tail": re.sub(r"\s+", " ", ss.get_text(" ", strip=True))[-1800:],
                })
            except Exception as exc:
                submit_tests.append({"name":name,"error":str(exc)})

    return {
        "status": r.status_code,
        "final_url": r.url,
        "content_type": r.headers.get("content-type"),
        "bytes": len(r.content),
        "title": soup.title.get_text(" ", strip=True) if soup.title else None,
        "href_count": len(hrefs),
        "forms": forms,
        "candidate_form": candidate_form,
        "submit_tests": submit_tests,
        "text_preview": re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:2600],
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
    field_values = [
        None,
        "*",
        "team",
        "reports",
        "seasons",
        "prices",
        "fitness",
        "*,team",
        "*,reports",
        "*,seasons",
        "*,reports,seasons",
        "*,team,reports,seasons,prices,fitness,competition",
    ]
    tests = []
    for fields in field_values:
        params = {"score":2,"lang":"en"}
        name = "minimal" if fields is None else "fields_" + fields.replace("*","star").replace(",","_")
        if fields is not None:
            params["fields"] = fields
        try:
            r = requests.get(base, params=params, headers=referer_headers, timeout=30, allow_redirects=True)
            rec = {"name":name,"fields":fields,"status":r.status_code,"final_url":r.url,"content_type":r.headers.get("content-type"),"bytes":len(r.content),"body_preview":r.text[:900]}
            try:
                obj=r.json()
                data=(obj.get("data") or {}) if isinstance(obj,dict) else None
                rec["top_keys"] = sorted(obj.keys()) if isinstance(obj,dict) else None
                rec["data_keys"] = sorted(data.keys()) if isinstance(data,dict) else None
                if isinstance(data,dict):
                    for key in ["reports","seasons","prices","fitness","competition","team"]:
                        if key in data:
                            v=data[key]
                            rec[key+"_type"] = type(v).__name__
                            rec[key+"_len"] = len(v) if isinstance(v,(list,dict)) else None
            except Exception:
                pass
            tests.append(rec)
        except Exception as exc:
            tests.append({"name":name,"fields":fields,"error":str(exc)})
    return {"sample_slug":slug,"tests":tests}


def main():
    c = probe_comunio()
    bcat, sample = get_biwenger_catalog()
    bdetail = probe_biwenger_detail(sample)
    print(json.dumps({"comunio":c,"biwenger_catalog":bcat,"biwenger_detail":bdetail}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
