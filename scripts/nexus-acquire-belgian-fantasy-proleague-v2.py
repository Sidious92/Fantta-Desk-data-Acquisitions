from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

OUT=Path(os.environ.get('NEXUS_BELGIAN_FANTASY_V2_OUT','/mnt/data/nexus-belgian-fantasy-proleague-v2'))
API='https://proleague.code.brussels'
FEED='JPL'
SEASON=2027
EXCEL='https://fanarena.s3.eu-west-1.amazonaws.com/files/spelers_JPL_2027.xlsx'
FDR='https://fanarena.s3.eu-west-1.amazonaws.com/players_JPL_2027.json'
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept':'application/json, text/plain, */*','Referer':'https://fantasy.proleague.be/'}

def now(): return datetime.now(timezone.utc).isoformat()
def mkdir(p): p.mkdir(parents=True,exist_ok=True); return p
def sha(b): return hashlib.sha256(b).hexdigest()
def dump(p,o): mkdir(p.parent); p.write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def get(url,params=None,attempts=4):
    last=None
    for i in range(attempts):
        try:
            r=requests.get(url,params=params or {},headers=HEADERS,timeout=40,allow_redirects=True)
            if r.status_code==200: return r
            last=RuntimeError(f'HTTP_{r.status_code} {r.url} {r.text[:250]!r}')
        except Exception as exc:last=exc
        time.sleep(min(2.5,0.35*(2**i)))
    raise last or RuntimeError('request failed')
def write_csv(p,rows):
    mkdir(p.parent)
    if not rows:p.write_text('',encoding='utf-8');return
    fs=[];seen=set()
    for r in rows:
        for k in r:
            if k not in seen:seen.add(k);fs.append(k)
    with p.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fs);w.writeheader();w.writerows(rows)
def flatten(obj,prefix=''):
    out={}
    if isinstance(obj,dict):
        for k,v in obj.items():
            key=f'{prefix}.{k}' if prefix else str(k)
            if isinstance(v,(dict,list)): out.update(flatten(v,key))
            else: out[key]=v
    elif isinstance(obj,list):
        for i,v in enumerate(obj):
            key=f'{prefix}[{i}]'
            if isinstance(v,(dict,list)):out.update(flatten(v,key))
            else:out[key]=v
    return out
def find_player_list(obj:Any):
    if isinstance(obj,list) and obj and all(isinstance(x,dict) for x in obj):
        # Prefer lists that look player-like.
        keys=set().union(*(x.keys() for x in obj[:20]))
        if keys & {'id','playerId','name','firstName','lastName','positionId','clubId'}: return obj
    if isinstance(obj,dict):
        preferred=['players','data','items','records','results','content']
        for k in preferred:
            if k in obj:
                r=find_player_list(obj[k])
                if r:return r
        for v in obj.values():
            r=find_player_list(v)
            if r:return r
    return []
def player_id(p):
    for k in ['id','playerId','player_id','playerID']:
        v=p.get(k) if isinstance(p,dict) else None
        if isinstance(v,int) or (isinstance(v,str) and v.isdigit()):return int(v)
    return None

def main():
    if OUT.exists():shutil.rmtree(OUT)
    raw=mkdir(OUT/'raw'); norm=mkdir(OUT/'normalized'); started=now()
    manifest={'schema':'NEXUS_BELGIAN_FANTASY_PROLEAGUE_V2','capture_started':started,'provider':'Fantasy Pro League','competitionFeed':FEED,'seasonId':SEASON,'sources':{},'governance':{'authenticated_surface_accessed':False,'private_team_or_user_endpoints_accessed':False,'cross_provider_normalization_performed':False,'missing_values_filled':False,'predictive_models_modified':False,'decision_layer_started':False}}

    # Public XLSX.
    xr=get(EXCEL); xb=xr.content; xlsx=raw/'spelers_JPL_2027.xlsx'; xlsx.write_bytes(xb)
    xlsx_valid=xb[:4]==b'PK\x03\x04'
    manifest['sources']['excel']={'url':xr.url,'status':xr.status_code,'bytes':len(xb),'sha256':sha(xb),'valid_xlsx':xlsx_valid,'local_path':str(xlsx.relative_to(OUT))}

    # Public FDR/player JSON.
    fr=get(FDR); fb=fr.content; fdr_path=raw/'players_JPL_2027.json'; fdr_path.write_bytes(fb)
    try:fdr_obj=fr.json();fdr_valid=True
    except Exception:fdr_obj=None;fdr_valid=False
    manifest['sources']['fdr']={'url':fr.url,'status':fr.status_code,'bytes':len(fb),'sha256':sha(fb),'valid_json':fdr_valid,'local_path':str(fdr_path.relative_to(OUT))}

    # Public players-stats API. First ask for a large page; if pagination remains, continue.
    pages=[];players_by_id={};all_rows=[];field_set=set()
    page=1;page_size=1000
    for _ in range(30):
        params={'competitionFeed':FEED,'seasonId':SEASON,'pageNumber':page,'pageRecords':page_size}
        r=get(f'{API}/players-stats',params); b=r.content
        pth=mkdir(raw/'players-stats')/f'page-{page:02d}.json';pth.write_bytes(b)
        try:obj=r.json()
        except Exception as exc:
            pages.append({'page':page,'status':r.status_code,'url':r.url,'bytes':len(b),'sha256':sha(b),'error':f'NON_JSON:{exc}'});break
        arr=find_player_list(obj)
        pages.append({'page':page,'status':r.status_code,'url':r.url,'bytes':len(b),'sha256':sha(b),'rows':len(arr),'top_type':type(obj).__name__,'top_keys':sorted(obj.keys()) if isinstance(obj,dict) else None})
        new=0
        for p in arr:
            if not isinstance(p,dict):continue
            field_set.update(p.keys());pid=player_id(p)
            key=str(pid) if pid is not None else hashlib.sha1(json.dumps(p,sort_keys=True,default=str).encode()).hexdigest()
            if key not in players_by_id:new+=1;players_by_id[key]=p
            all_rows.append({'provider':'FANTASY_PRO_LEAGUE','competition':'Jupiler Pro League','season_id':SEASON,'provider_player_id':pid,'source_url':r.url,'source_sha256':sha(b),'provider_fields_json':json.dumps(p,ensure_ascii=False,default=str,separators=(',',':')),**{k:v for k,v in p.items() if not isinstance(v,(dict,list))}})
        if not arr or new==0 or len(arr)<page_size:break
        page+=1
    dump(OUT/'players-stats-pages.json',pages);write_csv(norm/'players-stats.csv',all_rows)

    # Read-only player detail for discovered IDs only.
    detail_rows=[];detail_errors=[];detail_field_set=set();details=mkdir(raw/'player-details')
    ids=sorted({player_id(x) for x in players_by_id.values() if player_id(x) is not None})
    def one(pid):
        url=f'{API}/player/{pid}'
        try:
            r=get(url,{'withAggregatedWeekStats':1,'withStats':1});b=r.content
            try:o=r.json()
            except Exception as exc:return {'id':pid,'url':r.url,'error':f'NON_JSON:{exc}'}
            p=details/f'{pid}.json';p.write_bytes(b)
            return {'id':pid,'obj':o,'url':r.url,'sha256':sha(b),'path':p}
        except Exception as exc:return {'id':pid,'url':url,'error':str(exc)}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs=[ex.submit(one,pid) for pid in ids]
        for fut in as_completed(futs):
            x=fut.result();pid=x['id']
            if x.get('error'):detail_errors.append({'provider_player_id':pid,'url':x.get('url'),'error':x['error']});continue
            o=x['obj'];flat=flatten(o);detail_field_set.update(flat.keys())
            detail_rows.append({'provider':'FANTASY_PRO_LEAGUE','competition':'Jupiler Pro League','season_id':SEASON,'provider_player_id':pid,'source_url':x['url'],'source_sha256':x['sha256'],'source_local_path':str(x['path'].relative_to(OUT)),'provider_fields_json':json.dumps(o,ensure_ascii=False,default=str,separators=(',',':'))})
    write_csv(norm/'player-detail-index.csv',detail_rows);dump(OUT/'player-detail-errors.json',detail_errors)

    # Other read-only public signals; failures are diagnostic, never fatal by themselves.
    public_reads=[]
    for path,params in [
        ('points-confirmation',{'competitionFeed':FEED,'seasonId':SEASON}),
        ('matches/info',{'competitionFeed':FEED,'seasonId':SEASON}),
        ('clubs',{'competitionFeed':FEED,'seasonId':SEASON}),
    ]:
        try:
            r=get(f'{API}/{path}',params);b=r.content;p=raw/(path.replace('/','-')+'.json');p.write_bytes(b)
            public_reads.append({'endpoint':path,'status':r.status_code,'url':r.url,'bytes':len(b),'sha256':sha(b),'local_path':str(p.relative_to(OUT))})
        except Exception as exc:public_reads.append({'endpoint':path,'error':str(exc)})

    detail_rate=len(detail_rows)/len(ids) if ids else 0.0
    manifest['sources']['players_stats']={'pages':pages,'unique_player_ids':len(ids),'row_occurrences':len(all_rows),'field_inventory':sorted(field_set)}
    manifest['sources']['player_details']={'requested':len(ids),'ok':len(detail_rows),'errors':len(detail_errors),'success_rate':detail_rate,'flattened_field_inventory':sorted(detail_field_set)}
    manifest['sources']['additional_public_reads']=public_reads
    manifest['capture_completed']=now()
    manifest['status']='PASS' if xlsx_valid and fdr_valid and len(ids)>100 and detail_rate>=0.90 else 'FAIL_VALIDATION'
    dump(OUT/'manifest.json',manifest)
    inv=[]
    for p in sorted(x for x in OUT.rglob('*') if x.is_file()):
        if p.name=='file-inventory.json':continue
        inv.append({'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    dump(OUT/'file-inventory.json',inv)
    print(json.dumps({'status':manifest['status'],'xlsx':manifest['sources']['excel'],'fdr':manifest['sources']['fdr'],'players':len(ids),'detail_ok':len(detail_rows),'detail_errors':len(detail_errors),'pages':pages,'additional_reads':public_reads,'files':len(inv)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
