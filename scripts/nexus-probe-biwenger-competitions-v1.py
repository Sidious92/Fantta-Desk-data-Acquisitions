from __future__ import annotations

import json
from pathlib import Path
import requests

OUT = Path('.nexus-probe-biwenger-competitions-v1-status/RESULT.json')
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151.0 Safari/537.36',
    'Accept': 'application/json, text/plain, */*',
    'Referer': 'https://biwenger.as.com/',
}
CANDIDATES = [
    ('LaLiga','la-liga'),
    ('Premier League','premier-league'),
    ('Serie A','serie-a'),
    ('Ligue 1','ligue-1'),
    ('Liga Portugal','liga-portugal'),
    ('Segunda Division','segunda-division'),
    ('Champions League','champions-league'),
    ('Liga MX','liga-mx'),
    ('World Cup','world-cup'),
    ('Mundial','mundial'),
]


def main():
    results=[]
    for name,slug in CANDIDATES:
        url=f'https://cf.biwenger.com/api/v2/competitions/{slug}/data'
        try:
            r=requests.get(url,params={'lang':'en','score':2},headers=HEADERS,timeout=30)
            rec={'name':name,'slug':slug,'status':r.status_code,'url':r.url,'bytes':len(r.content)}
            try:
                obj=r.json()
                data=(obj.get('data') or {}) if isinstance(obj,dict) else {}
                players=data.get('players') if isinstance(data,dict) else None
                teams=data.get('teams') if isinstance(data,dict) else None
                if isinstance(players,dict): pcount=len(players)
                elif isinstance(players,list): pcount=len(players)
                else: pcount=0
                if isinstance(teams,dict): tcount=len(teams)
                elif isinstance(teams,list): tcount=len(teams)
                else: tcount=0
                rec.update({
                    'api_status':obj.get('status') if isinstance(obj,dict) else None,
                    'data_keys':sorted(data.keys()) if isinstance(data,dict) else [],
                    'players':pcount,
                    'teams':tcount,
                    'valid':r.status_code==200 and pcount>0,
                })
                if pcount:
                    iterable=list(players.values()) if isinstance(players,dict) else players
                    sample=next((p for p in iterable if isinstance(p,dict)),{})
                    rec['player_fields']=sorted(sample.keys())
                    rec['sample_player']={k:sample.get(k) for k in ['id','name','slug','teamID','points','pointsLastSeason']}
            except Exception:
                rec['valid']=False
                rec['body_preview']=r.text[:300]
            results.append(rec)
        except Exception as exc:
            results.append({'name':name,'slug':slug,'valid':False,'error':str(exc)})
    payload={
        'schema':'NEXUS_BIWENGER_COMPETITION_PROBE_V1',
        'results':results,
        'valid_slugs':[r['slug'] for r in results if r.get('valid')],
    }
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
