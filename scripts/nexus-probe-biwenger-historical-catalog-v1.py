from __future__ import annotations
import json
from pathlib import Path
import requests

OUT=Path('.nexus-probe-biwenger-historical-catalog-v1-status/RESULT.json')
HEADERS={'User-Agent':'Mozilla/5.0 Chrome/151','Accept':'application/json, text/plain, */*','Referer':'https://biwenger.as.com/'}
COMPS=['la-liga','premier-league','segunda-division','serie-a','ligue-1','primeira-liga','liga-mx','champions-league','copa-del-rey','world-cup']
SEASONS=[2022,2023,2024,2025,2026]

def req(slug,season):
    url=f'https://cf.biwenger.com/api/v2/competitions/{slug}/data'
    try:
        r=requests.get(url,params={'lang':'en','season':season},headers=HEADERS,timeout=30)
        rec={'slug':slug,'query_season':season,'status':r.status_code,'url':r.url,'bytes':len(r.content)}
        try: obj=r.json()
        except Exception: return rec
        data=(obj.get('data') or {}) if isinstance(obj,dict) else {}
        if isinstance(data,dict):
            players=data.get('players') or {}
            teams=data.get('teams') or {}
            seas=data.get('season') or {}
            rec.update({
                'api_status':obj.get('status'),
                'data_season_id':seas.get('id') if isinstance(seas,dict) else None,
                'data_season_name':seas.get('name') if isinstance(seas,dict) else None,
                'data_season_slug':seas.get('slug') if isinstance(seas,dict) else None,
                'players':len(players) if isinstance(players,(dict,list)) else 0,
                'teams':len(teams) if isinstance(teams,(dict,list)) else 0,
                'scoreID':data.get('scoreID'),
                'verified':str(seas.get('id'))==str(season) if isinstance(seas,dict) else False,
            })
        return rec
    except Exception as exc:
        return {'slug':slug,'query_season':season,'error':str(exc),'verified':False}

def main():
    rows=[req(c,s) for c in COMPS for s in SEASONS]
    payload={'schema':'NEXUS_BIWENGER_HISTORICAL_CATALOG_PROBE_V1','results':rows}
    payload['verified_scopes']=[f"{r['slug']}:{r['query_season']}" for r in rows if r.get('verified') and r.get('players',0)>0]
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'verified_count':len(payload['verified_scopes']),'verified_scopes':payload['verified_scopes']},indent=2))
if __name__=='__main__': main()
