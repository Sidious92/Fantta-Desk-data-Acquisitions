from __future__ import annotations

import json
import time
from pathlib import Path

import requests

OUT = Path('.nexus-probe-biwenger-competitions-v2-status/RESULT.json')
BASE = 'https://cf.biwenger.com/api/v2/competitions/{slug}/data'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://biwenger.as.com/',
}

# Web-route slugs verified/discovered from Biwenger public pages/search.
COMPETITIONS = [
    ('LaLiga', 'la-liga'),
    ('Premier League', 'premier-league'),
    ('Segunda Division', 'segunda-division'),
    ('Serie A', 'serie-a'),
    ('Ligue 1', 'ligue-1'),
    ('Liga Portugal', 'primeira-liga'),
    ('Liga MX', 'liga-mx'),
    ('Champions League', 'champions-league'),
    ('Copa del Rey', 'copa-del-rey'),
    ('World Cup', 'world-cup'),
]


def probe(name: str, slug: str):
    results=[]
    candidates=[None] + list(range(1, 13))
    for score in candidates:
        params={'lang':'en'}
        if score is not None:
            params['score']=score
        try:
            r=requests.get(BASE.format(slug=slug), params=params, headers=HEADERS, timeout=30)
            rec={'score':score,'status':r.status_code,'url':r.url,'bytes':len(r.content)}
            try:
                obj=r.json()
            except Exception:
                obj=None
            if isinstance(obj,dict):
                rec['api_status']=obj.get('status')
                data=obj.get('data') or {}
                if isinstance(data,dict):
                    players=data.get('players') or {}
                    teams=data.get('teams') or {}
                    rec['data_slug']=data.get('slug')
                    rec['competition_id']=data.get('id')
                    rec['season']=data.get('season')
                    rec['scoreID']=data.get('scoreID')
                    rec['scores']=data.get('scores')
                    rec['players']=len(players) if isinstance(players,(dict,list)) else 0
                    rec['teams']=len(teams) if isinstance(teams,(dict,list)) else 0
                    rec['valid']=r.status_code==200 and rec['players']>0
            results.append(rec)
        except Exception as exc:
            results.append({'score':score,'error':str(exc),'valid':False})
        time.sleep(0.05)
    valid=[r for r in results if r.get('valid')]
    return {
        'name':name,
        'web_slug':slug,
        'valid':bool(valid),
        'valid_score_queries':[r.get('score') for r in valid],
        'canonical_data_slugs':sorted({str(r.get('data_slug')) for r in valid if r.get('data_slug')}),
        'competition_ids':sorted({str(r.get('competition_id')) for r in valid if r.get('competition_id') is not None}),
        'results':results,
    }


def main():
    payload={
        'schema':'NEXUS_BIWENGER_COMPETITION_PROBE_V2',
        'results':[probe(name,slug) for name,slug in COMPETITIONS],
    }
    payload['valid_competitions']=[x['name'] for x in payload['results'] if x['valid']]
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({
        'schema':payload['schema'],
        'valid_competitions':payload['valid_competitions'],
        'summary':[{k:x.get(k) for k in ['name','web_slug','valid','valid_score_queries','canonical_data_slugs','competition_ids']} for x in payload['results']],
    },ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
