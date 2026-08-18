from __future__ import annotations
import json
from pathlib import Path
import requests

OUT=Path('.nexus-probe-biwenger-seriea-crossleague-history-v1-status/RESULT.json')
HEADERS={'User-Agent':'Mozilla/5.0 Chrome/151','Accept':'application/json, text/plain, */*','Referer':'https://biwenger.as.com/serie-a/players/'}
BASE='https://cf.biwenger.com/api/v2'
TARGET_NAMES=['Malen','David','Hojlund','Højlund','Kean','Lautaro Martínez','Nkunku','De Bruyne']
SEASON_IDS=['2022','2023','2024','2025','2026']
FIELDS='*,team,reports,seasons,competition,fitness'

def get_json(url,params=None):
    r=requests.get(url,params=params or {},headers=HEADERS,timeout=30)
    try: obj=r.json()
    except Exception: obj=None
    return r,obj

def main():
    r,obj=get_json(f'{BASE}/competitions/serie-a/data',{'lang':'en'})
    data=(obj.get('data') or {}) if isinstance(obj,dict) else {}
    players=data.get('players') or {}
    arr=list(players.values()) if isinstance(players,dict) else players if isinstance(players,list) else []
    selected=[]
    for p in arr:
        name=str(p.get('name') or '')
        if any(t.casefold() in name.casefold() for t in TARGET_NAMES): selected.append(p)
    results=[]
    for p in selected:
        slug=p.get('slug')
        if not slug: continue
        rec={'catalog':{k:p.get(k) for k in ['id','name','slug','teamID','points','pointsLastSeason']},'seasons':[]}
        mr,mo=get_json(f'{BASE}/players/serie-a/{slug}',{'lang':'en','fields':'*,team,seasons,competition'})
        md=(mo.get('data') or {}) if isinstance(mo,dict) else {}
        rec['metadata_status']=mr.status_code
        rec['metadata_competition']=md.get('competition')
        rec['metadata_seasons']=md.get('seasons')
        for sid in SEASON_IDS:
            rr,oo=get_json(f'{BASE}/players/serie-a/{slug}',{'lang':'en','fields':FIELDS,'season':sid})
            d=(oo.get('data') or {}) if isinstance(oo,dict) else {}
            reports=d.get('reports') or []
            comp=d.get('competition')
            teams=[]; matches=[]; event_keys=set()
            for x in reports if isinstance(reports,list) else []:
                if not isinstance(x,dict): continue
                match=x.get('match') or {}
                for side in ['home','away']:
                    t=match.get(side)
                    if isinstance(t,dict) and t.get('name'): teams.append(t.get('name'))
                if isinstance(match,dict):
                    matches.append({k:match.get(k) for k in ['id','date','round'] if k in match})
                events=x.get('events')
                if isinstance(events,dict): event_keys.update(events.keys())
                elif isinstance(events,list):
                    for e in events:
                        if isinstance(e,dict): event_keys.update(e.keys())
            rec['seasons'].append({'season_id':sid,'status':rr.status_code,'reports_count':len(reports) if isinstance(reports,list) else 0,'competition':comp,'teams_sample':sorted(set(teams))[:12],'event_keys':sorted(event_keys),'reports_preview':reports[:2] if isinstance(reports,list) else None})
        results.append(rec)
    payload={'schema':'NEXUS_BIWENGER_SERIEA_CROSSLEAGUE_HISTORY_PROBE_V1','catalog_players':len(arr),'selected':results}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'catalog_players':len(arr),'players':[{'name':x['catalog']['name'],'season_counts':[(s['season_id'],s['reports_count'],s['teams_sample']) for s in x['seasons']]} for x in results]},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
