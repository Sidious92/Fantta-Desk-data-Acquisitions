from __future__ import annotations

import csv, hashlib, json, os, shutil, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

OUT=Path(os.environ.get('NEXUS_BELGIAN_V21_OUT','/mnt/data/nexus-belgian-fantasy-proleague-v2-1'))
API='https://proleague.code.brussels'; FEED='JPL'; SEASON=2027
EXCEL='https://fanarena.s3.eu-west-1.amazonaws.com/files/spelers_JPL_2027.xlsx'
FDR='https://fanarena.s3.eu-west-1.amazonaws.com/players_JPL_2027.json'
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept':'application/json, text/plain, */*','Referer':'https://fantasy.proleague.be/stats'}

def mkdir(p):p.mkdir(parents=True,exist_ok=True);return p
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def dump(p,o):mkdir(p.parent);p.write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def get(url,params=None,attempts=4,require_200=True):
    last=None
    for i in range(attempts):
        try:
            r=requests.get(url,params=params or {},headers=HEADERS,timeout=40,allow_redirects=True)
            if not require_200 or r.status_code==200:return r
            last=RuntimeError(f'HTTP_{r.status_code} {r.url} {r.text[:200]!r}')
        except Exception as exc:last=exc
        time.sleep(min(2.5,0.35*2**i))
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
def scalar(d):return {k:v for k,v in d.items() if not isinstance(v,(dict,list))}

def main():
    if OUT.exists():shutil.rmtree(OUT)
    raw=mkdir(OUT/'raw');norm=mkdir(OUT/'normalized');started=now()
    # S3 Excel is diagnostic only; never bypass a 403.
    er=get(EXCEL,require_200=False);excel={'url':er.url,'status':er.status_code,'bytes':len(er.content),'sha256':sha(er.content),'valid_xlsx':er.status_code==200 and er.content[:4]==b'PK\x03\x04'}
    (raw/'excel-response.bin').write_bytes(er.content)
    if excel['valid_xlsx']:(raw/'spelers_JPL_2027.xlsx').write_bytes(er.content)
    # FDR JSON is verified public and required.
    fr=get(FDR);fb=fr.content;fdr=fr.json();(raw/'players_JPL_2027.json').write_bytes(fb)
    fdr_meta={'url':fr.url,'status':fr.status_code,'bytes':len(fb),'sha256':sha(fb),'valid_json':isinstance(fdr,dict)}

    # Season player totals. Preserve both the opaque document id and numeric playerId.
    page=1;page_size=1000;pages=[];players={};occurrences=[];field_set=set();total_records=None
    for _ in range(50):
        params={'competitionFeed':FEED,'seasonId':SEASON,'pageNumber':page,'pageRecords':page_size}
        r=get(f'{API}/players-stats',params);b=r.content;o=r.json();path=mkdir(raw/'players-stats')/f'page-{page:02d}.json';path.write_bytes(b)
        arr=o.get('data') if isinstance(o,dict) else None
        if not isinstance(arr,list):arr=[]
        if isinstance(o,dict) and total_records is None:total_records=o.get('totalRecords')
        new=0
        for p in arr:
            if not isinstance(p,dict):continue
            field_set.update(p.keys());opaque=p.get('id')
            if opaque is None:continue
            key=str(opaque)
            if key not in players:new+=1;players[key]=p
            occurrences.append({'provider':'FANTASY_PRO_LEAGUE','competition':'Jupiler Pro League','season_id':SEASON,'provider_player_id':key,'provider_numeric_player_id':p.get('playerId'),'source_url':r.url,'source_sha256':sha(b),'provider_fields_json':json.dumps(p,ensure_ascii=False,default=str,separators=(',',':')),**scalar(p)})
        pages.append({'page':page,'status':r.status_code,'url':r.url,'bytes':len(b),'sha256':sha(b),'rows':len(arr),'new_ids':new,'totalRecords':o.get('totalRecords') if isinstance(o,dict) else None})
        if not arr or new==0 or (total_records is not None and len(players)>=int(total_records)) or len(arr)<page_size:break
        page+=1
    dump(OUT/'players-stats-pages.json',pages);write_csv(norm/'players-stats.csv',occurrences)

    # Public player details: frontend API uses numeric playerId, not the opaque document id.
    details=mkdir(raw/'player-details');detail_rows=[];detail_errors=[];detail_top_fields=set();stat_fields=set()
    def one(opaque,p):
        numeric=p.get('playerId')
        if numeric in (None,''):
            return {'id':opaque,'numeric_id':numeric,'error':'MISSING_playerId'}
        try:
            r=get(f'{API}/player/{numeric}',{'withAggregatedWeekStats':1,'withStats':1});b=r.content;o=r.json();lp=details/f'{opaque}.json';lp.write_bytes(b);return {'id':opaque,'numeric_id':numeric,'obj':o,'url':r.url,'sha256':sha(b),'path':lp}
        except Exception as exc:return {'id':opaque,'numeric_id':numeric,'error':str(exc)}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs=[ex.submit(one,opaque,p) for opaque,p in players.items()]
        for fut in as_completed(futs):
            x=fut.result();opaque=x['id'];numeric=x.get('numeric_id')
            if x.get('error'):detail_errors.append({'provider_player_id':opaque,'provider_numeric_player_id':numeric,'error':x['error']});continue
            o=x['obj']
            if isinstance(o,dict):
                detail_top_fields.update(o.keys())
                def walk(v):
                    if isinstance(v,dict):
                        for k,z in v.items():
                            if k.lower() in {'stats','aggregatedweekstats','weekstats'} and isinstance(z,(dict,list)):
                                if isinstance(z,dict):stat_fields.update(z.keys())
                                elif isinstance(z,list):
                                    for q in z:
                                        if isinstance(q,dict):stat_fields.update(q.keys())
                            walk(z)
                    elif isinstance(v,list):
                        for z in v:walk(z)
                walk(o)
            detail_rows.append({'provider':'FANTASY_PRO_LEAGUE','competition':'Jupiler Pro League','season_id':SEASON,'provider_player_id':opaque,'provider_numeric_player_id':numeric,'source_url':x['url'],'source_sha256':x['sha256'],'source_local_path':str(x['path'].relative_to(OUT)),'provider_fields_json':json.dumps(o,ensure_ascii=False,default=str,separators=(',',':'))})
    write_csv(norm/'player-detail-index.csv',detail_rows);dump(OUT/'player-detail-errors.json',detail_errors)

    # Public read endpoints referenced by frontend; pass required competition/season params.
    public_reads=[]
    for path,params in [('points-confirmation',{'competitionFeed':FEED,'seasonId':SEASON}),('matches/info',{'competitionFeed':FEED,'seasonId':SEASON}),('clubs',{'competitionFeed':FEED,'seasonId':SEASON})]:
        try:
            r=get(f'{API}/{path}',params);b=r.content;lp=raw/(path.replace('/','-')+'.json');lp.write_bytes(b);public_reads.append({'endpoint':path,'status':r.status_code,'url':r.url,'bytes':len(b),'sha256':sha(b),'local_path':str(lp.relative_to(OUT))})
        except Exception as exc:public_reads.append({'endpoint':path,'error':str(exc)})

    rate=len(detail_rows)/len(players) if players else 0
    manifest={'schema':'NEXUS_BELGIAN_FANTASY_PROLEAGUE_V2_1','status':'PASS' if len(players)>100 and rate>=0.90 and fdr_meta['valid_json'] else 'FAIL_VALIDATION','capture_started':started,'capture_completed':now(),'competitionFeed':FEED,'seasonId':SEASON,'sources':{'excel_optional_diagnostic':excel,'fdr_json':fdr_meta,'players_stats':{'pages':pages,'totalRecords':total_records,'unique_players':len(players),'row_occurrences':len(occurrences),'field_inventory':sorted(field_set)},'player_details':{'requested':len(players),'ok':len(detail_rows),'errors':len(detail_errors),'success_rate':rate,'top_level_fields':sorted(detail_top_fields),'nested_stat_fields':sorted(stat_fields)},'additional_public_reads':public_reads},'governance':{'opaque_string_player_ids_preserved':True,'numeric_player_ids_preserved':True,'excel_access_bypass_attempted':False,'authenticated_surface_accessed':False,'private_team_or_user_endpoints_accessed':False,'cross_provider_normalization_performed':False,'missing_values_filled':False,'predictive_models_modified':False,'decision_layer_started':False}}
    dump(OUT/'manifest.json',manifest)
    inv=[]
    for p in sorted(x for x in OUT.rglob('*') if x.is_file()):
        if p.name=='file-inventory.json':continue
        inv.append({'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    dump(OUT/'file-inventory.json',inv);print(json.dumps({'status':manifest['status'],'players':len(players),'details_ok':len(detail_rows),'detail_errors':len(detail_errors),'excel_status':excel['status'],'fdr':fdr_meta,'pages':pages,'files':len(inv)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
