from __future__ import annotations

import json
from pathlib import Path

import requests

OUT = Path('/mnt/data/nexus-additional-fantasy-public-probes-v1')
OUT.mkdir(parents=True, exist_ok=True)
UA = 'Mozilla/5.0 (compatible; FantaNexusResearch/1.0; public-source-probe)'


def record_get(name, url, headers=None):
    h={'User-Agent':UA,'Accept':'*/*'}
    if headers: h.update(headers)
    item={'name':name,'method':'GET','url':url}
    try:
        r=requests.get(url,headers=h,timeout=20,allow_redirects=True)
        item.update({'status':r.status_code,'final_url':r.url,'content_type':r.headers.get('content-type'),'bytes':len(r.content)})
        (OUT/f'{name}.body').write_bytes(r.content)
        item['body_file']=f'{name}.body'
        item['body_preview']=r.text[:1000] if 'text' in (r.headers.get('content-type') or '') or 'json' in (r.headers.get('content-type') or '') else None
    except Exception as exc:
        item['error']=str(exc)
    return item


def record_post_json(name,url,payload,headers=None):
    h={'User-Agent':UA,'Accept':'application/json','Content-Type':'application/json'}
    if headers: h.update(headers)
    item={'name':name,'method':'POST','url':url,'payload':payload}
    try:
        r=requests.post(url,headers=h,json=payload,timeout=20,allow_redirects=True)
        item.update({'status':r.status_code,'final_url':r.url,'content_type':r.headers.get('content-type'),'bytes':len(r.content)})
        (OUT/f'{name}.body').write_bytes(r.content)
        item['body_file']=f'{name}.body'
        item['body_preview']=r.text[:2000]
    except Exception as exc:
        item['error']=str(exc)
    return item


results=[]
laliga_headers={
    'Origin':'https://fantasy.laliga.com',
    'Referer':'https://fantasy.laliga.com/',
    'X-App':'Fantasy-web',
    'X-Lang':'es',
}
results.append(record_get('laliga_fantasy_player_52','https://api.laligafantasymarca.com/api/v3/player/52',laliga_headers))
results.append(record_get('laliga_fantasy_player_52_market_value','https://api.laligafantasymarca.com/api/v3/player/52/market-value',laliga_headers))
results.append(record_get('sorare_graphql_schema','https://api.sorare.com/graphql/schema'))
results.append(record_post_json('sorare_anonymous_introspection','https://api.sorare.com/graphql',{'query':'query { __schema { queryType { fields { name } } } }'}))
results.append(record_get('kickbase_competition_players_probe','https://api.kickbase.com/v4/competitions/1/players'))

# A probe is informational: HTTP 401/403 is a valid determination that a
# provider is not anonymous. Only network/execution failure is recorded as such.
summary={'schema':'NEXUS_ADDITIONAL_FANTASY_PUBLIC_PROBES_V1','results':results}
(OUT/'probe-results.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
