#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import requests

SRC = Path('.nexus-ligue1-historical-calendar-v2-status/RESULT.json')
OUT = Path('/mnt/data/nexus-ligue1-historical-match-v3')
OUT.mkdir(parents=True, exist_ok=True)
API = 'https://api.mpg.football/fantasy'
HEADERS = {
    'User-Agent':'Mozilla/5.0 FantaNexus research acquisition',
    'Accept':'application/json,text/plain,*/*',
    'Referer':'https://ligue1.com/en/fantasy',
    'platform':'web',
    'application':'ligue1',
}

def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def first_observed_match_id(obj):
    # Use only the persisted historical 2025 payload and its exact `matchesIds` values.
    for rec in obj.get('results', []):
        if rec.get('label') != 'observed_first_season':
            continue
        payload = rec.get('json')
        if not isinstance(payload, dict):
            continue
        for gw in payload.get('gameWeeks') or []:
            if isinstance(gw, dict):
                ids = gw.get('matchesIds')
                if isinstance(ids, list) and ids and isinstance(ids[0], (str,int)):
                    return ids[0], gw.get('gameWeekNumber')
    return None, None


def inspect(obj):
    keys=set(); leaf_keys=set(); numeric=[]; arrays=[]
    def walk(x,path='$'):
        if isinstance(x,dict):
            keys.update(map(str,x.keys()))
            for k,v in x.items():
                if isinstance(v,(dict,list)): walk(v,f'{path}.{k}')
                else:
                    leaf_keys.add(str(k))
                    if isinstance(v,(int,float)) and not isinstance(v,bool):
                        numeric.append({'path':f'{path}.{k}','key':k,'value':v})
        elif isinstance(x,list):
            arrays.append({'path':path,'rows':len(x),'sample_type':type(x[0]).__name__ if x else None})
            for i,v in enumerate(x[:200]):
                if isinstance(v,(dict,list)): walk(v,f'{path}[{i}]')
    walk(obj)
    fantasy_signals=[k for k in sorted(keys) if any(t in k.lower() for t in ['rating','point','score','goal','assist','card','bonus','minute','player','event','stat'])]
    return {'all_keys':sorted(keys),'leaf_keys':sorted(leaf_keys),'fantasy_or_stat_signal_keys':fantasy_signals,'arrays':arrays[:100],'numeric_samples':numeric[:200]}

src=json.loads(SRC.read_text(encoding='utf-8'))
match_id, gw = first_observed_match_id(src)
if match_id is None:
    raise SystemExit('FAIL_CLOSED_NO_OBSERVED_HISTORICAL_MATCH_ID')
route=f'/match-sheet/{quote(str(match_id), safe="")}/match-history'
r=requests.get(API+route,headers=HEADERS,timeout=(8,30),allow_redirects=True)
raw=r.content
result={
    'schema':'NEXUS_LIGUE1_HISTORICAL_MATCH_PROBE_V3',
    'observed_source':{'season':2025,'game_week':gw,'match_id':match_id},
    'request':{'route':route,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(raw),'sha256':sha(raw)},
    'governance':{
        'route_template_source':'frontend-observed-v1',
        'match_id_source':'historical-calendar-v2-observed-matchesIds',
        'match_id_guessed':False,
        'authenticated_surface_accessed':False,
        'private_user_or_coach_routes_accessed':False,
        'predictive_models_modified':False,
        'decision_layer_started':False,
    }
}
try:
    obj=r.json();result['json_type']=type(obj).__name__;result['json_keys']=list(obj)[:100] if isinstance(obj,dict) else None;result['inspection']=inspect(obj);result['json']=obj
except Exception as e:
    result['json_error']=repr(e);result['preview']=r.text[:2000]
result['status']='PASS_MATCH_HISTORY' if r.status_code==200 and 'json' in result else 'FAIL_CLOSED_MATCH_HISTORY'
(OUT/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k!='json'},ensure_ascii=False,indent=2))
