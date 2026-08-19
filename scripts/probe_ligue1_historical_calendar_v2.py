#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import urlencode

import requests

SRC = Path('.nexus-ligue1-historical-contract-v1-status/RESULT.json')
OUT = Path('/mnt/data/nexus-ligue1-historical-calendar-v2')
OUT.mkdir(parents=True, exist_ok=True)
API = 'https://api.mpg.football/fantasy'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 FantaNexus research acquisition',
    'Accept': 'application/json,text/plain,*/*',
    'Referer': 'https://ligue1.com/en/fantasy',
    'platform': 'web',
    'application': 'ligue1',
}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def find_settings(obj):
    settings = (((obj.get('settings') or {}).get('json')) if isinstance(obj.get('settings'), dict) else None)
    if isinstance(settings, dict):
        cs = settings.get('championshipsSettings')
        if isinstance(cs, dict) and isinstance(cs.get('1'), dict):
            return cs['1']
    # v1 deliberately omitted full settings JSON from top-level result; reconstruct only
    # season facts from its persisted, observed season nodes.
    vals = {}
    for row in obj.get('settings_season_nodes', []):
        p = row.get('path')
        if p == '$.championshipsSettings.1.season': vals['season'] = row.get('value')
        if p == '$.championshipsSettings.1.firstSeason': vals['firstSeason'] = row.get('value')
    return vals


def inspect(obj):
    counts = {'dicts': 0, 'lists': 0, 'scalars': 0}
    match_like = []
    ids = []
    def walk(x, path='$'):
        if isinstance(x, dict):
            counts['dicts'] += 1
            keys = set(x.keys())
            lower = {str(k).lower() for k in keys}
            if any(k in lower for k in ['matchid','match_id','fixtureid','fixture_id']) or ({'home', 'away'} <= lower) or ({'hometeam', 'awayteam'} <= lower):
                match_like.append({'path': path, 'keys': sorted(map(str, keys))[:100], 'sample': {k:v for k,v in x.items() if not isinstance(v,(dict,list))}})
            for k, v in x.items():
                kl = str(k).lower()
                if kl in {'matchid','match_id','fixtureid','fixture_id'} and isinstance(v, (str,int)):
                    ids.append({'path': f'{path}.{k}', 'key': k, 'value': v})
                if isinstance(v, (dict,list)): walk(v, f'{path}.{k}')
                else: counts['scalars'] += 1
        elif isinstance(x, list):
            counts['lists'] += 1
            for i, v in enumerate(x):
                if isinstance(v, (dict,list)): walk(v, f'{path}[{i}]')
                else: counts['scalars'] += 1
    walk(obj)
    unique=[]; seen=set()
    for r in ids:
        key=(r['key'], str(r['value']))
        if key not in seen:
            seen.add(key); unique.append(r)
    return {'counts':counts,'match_like_count':len(match_like),'match_like_samples':match_like[:30],'observed_match_ids':unique[:100]}


src = json.loads(SRC.read_text(encoding='utf-8'))
settings = find_settings(src)
current = settings.get('season')
first = settings.get('firstSeason')
if not isinstance(current, int) or not isinstance(first, int):
    raise SystemExit(f'FAIL_CLOSED: observed season values unavailable: {settings!r}')
if first == current:
    raise SystemExit('FAIL_CLOSED: firstSeason equals current season')

results=[]
for label, season in [('current_control', current), ('observed_first_season', first)]:
    route = '/championship-calendar/1?' + urlencode({'season': season})
    r = requests.get(API + route, headers=HEADERS, timeout=(8,30), allow_redirects=True)
    raw=r.content
    rec={'label':label,'season':season,'route':route,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(raw),'sha256':sha(raw)}
    try:
        obj=r.json(); rec['json_type']=type(obj).__name__; rec['json_keys']=list(obj)[:100] if isinstance(obj,dict) else None; rec['inspection']=inspect(obj); rec['json']=obj
    except Exception as e:
        rec['json_error']=repr(e);rec['preview']=r.text[:1000]
    results.append(rec)

historical=results[1];control=results[0]
distinct = historical.get('sha256') != control.get('sha256')
hist_ok = historical.get('status') == 200 and 'json' in historical
status='PASS_HISTORICAL_CALENDAR' if hist_ok and distinct else ('PASS_SAME_PAYLOAD' if hist_ok else 'FAIL_CLOSED')
result={
    'schema':'NEXUS_LIGUE1_HISTORICAL_CALENDAR_PROBE_V2',
    'status':status,
    'observed_settings':{'championship_id':1,'current_season':current,'first_season':first},
    'results':results,
    'historical_distinct_from_current':distinct,
    'governance':{
        'route_template_source':'frontend-observed-v1',
        'championship_id_source':'existing verified Ligue 1 contract',
        'season_values_source':'public championships-settings via v1',
        'season_ids_guessed':False,
        'authenticated_surface_accessed':False,
        'private_user_or_coach_routes_accessed':False,
        'predictive_models_modified':False,
        'decision_layer_started':False,
    }
}
(OUT/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({
    'status':status,
    'settings':result['observed_settings'],
    'tests':[{k:v for k,v in x.items() if k not in ['json']} for x in results],
},ensure_ascii=False,indent=2))
