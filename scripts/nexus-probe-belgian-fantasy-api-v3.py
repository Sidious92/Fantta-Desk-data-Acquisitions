from __future__ import annotations
import json
from pathlib import Path
import requests

OUT=Path('.nexus-probe-belgian-fantasy-api-v3-status/RESULT.json')
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept':'application/json, text/plain, */*','Referer':'https://fantasy.proleague.be/stats'}

def test(url,params=None):
    try:
        r=requests.get(url,params=params or {},headers=HEADERS,timeout=35,allow_redirects=True)
        rec={'url':url,'status':r.status_code,'final_url':r.url,'content_type':r.headers.get('content-type'),'bytes':len(r.content),'prefix_hex':r.content[:8].hex(),'preview':r.text[:1200] if 'json' in (r.headers.get('content-type') or '').lower() or 'text' in (r.headers.get('content-type') or '').lower() or len(r.content)<3000 else None}
        try:
            o=r.json();rec['json_type']=type(o).__name__;rec['json_keys']=sorted(o.keys()) if isinstance(o,dict) else None;rec['json_len']=len(o) if isinstance(o,(dict,list)) else None
            if isinstance(o,dict):
                rec['shape_preview']={k:(type(v).__name__,len(v) if isinstance(v,(dict,list)) else None) for k,v in o.items()}
        except Exception:pass
        return rec
    except Exception as exc:return {'url':url,'error':str(exc)}

def main():
    tests=[]
    tests.append(test('https://proleague.code.brussels/players-stats',{'competitionFeed':'JPL','seasonId':2027,'pageNumber':1,'pageRecords':10}))
    tests.append(test('https://proleague.code.brussels/points-confirmation',{'competitionFeed':'JPL','seasonId':2027}))
    for url in [
        'https://fanarena.s3.eu-west-1.amazonaws.com/files/spelers_JPL_2027.xlsx',
        'https://s3-eu-west-1.amazonaws.com/fanarena/files/spelers_JPL_2027.xlsx',
        'https://fanarena.s3.eu-west-1.amazonaws.com/players_JPL_2027.json',
        'https://s3-eu-west-1.amazonaws.com/fanarena/players_JPL_2027.json',
    ]:tests.append(test(url))
    payload={'schema':'NEXUS_BELGIAN_FANTASY_API_PROBE_V3','tests':tests}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps(payload,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
