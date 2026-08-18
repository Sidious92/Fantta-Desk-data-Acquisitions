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

OUT = Path(os.environ.get('NEXUS_BIWENGER_SERIEA_HISTORY_OUT','/mnt/data/nexus-biwenger-seriea-crossleague-history-v1'))
BASE='https://cf.biwenger.com/api/v2'
TARGET_SEASON_IDS={'2022':'2021-22','2023':'2022-23','2024':'2023-24','2025':'2024-25','2026':'2025-26'}
FIELDS_METADATA='*,team,seasons,competition'
FIELDS_HISTORY='*,team,reports,seasons,competition,fitness'
HEADERS={
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36',
    'Accept':'application/json, text/plain, */*',
    'Referer':'https://biwenger.as.com/serie-a/players/',
}


def now_iso(): return datetime.now(timezone.utc).isoformat()
def mkdir(p:Path): p.mkdir(parents=True,exist_ok=True); return p
def sha_bytes(b:bytes): return hashlib.sha256(b).hexdigest()
def write_json(p:Path,obj:Any): mkdir(p.parent); p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')

def request_json(url:str,params:dict|None=None,attempts:int=4):
    last=None
    for i in range(attempts):
        try:
            r=requests.get(url,params=params or {},headers=HEADERS,timeout=35)
            raw=r.content
            try: obj=r.json()
            except Exception: obj=None
            if r.status_code==200 and isinstance(obj,dict): return obj,raw,r.url,r.status_code
            last=RuntimeError(f'HTTP_{r.status_code} {r.url} body={r.text[:200]!r}')
        except Exception as exc: last=exc
        time.sleep(min(2.0,0.35*(2**i)))
    raise last or RuntimeError('request failed')

def player_array(data):
    p=(data or {}).get('players') or {}
    if isinstance(p,dict): return [x for x in p.values() if isinstance(x,dict)]
    if isinstance(p,list): return [x for x in p if isinstance(x,dict)]
    return []

def write_csv(path:Path,rows:list[dict]):
    mkdir(path.parent)
    if not rows: path.write_text('',encoding='utf-8'); return
    fields=[]; seen=set()
    for r in rows:
        for k in r:
            if k not in seen: seen.add(k); fields.append(k)
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def competition_class(slug:str|None):
    if slug in {'champions-league','europa-league','conference-league'}: return 'UEFA_CLUB'
    if slug in {'world-cup','euro','club-world-cup'}: return 'INTERNATIONAL_OR_GLOBAL'
    return 'DOMESTIC_OR_PROVIDER_COMPETITION'

def main():
    if OUT.exists(): shutil.rmtree(OUT)
    mkdir(OUT)
    started=now_iso()
    raw_root=mkdir(OUT/'raw')
    metadata_root=mkdir(raw_root/'player-metadata')
    history_root=mkdir(raw_root/'history')
    normalized=mkdir(OUT/'normalized')

    cat_obj,cat_raw,cat_url,cat_status=request_json(f'{BASE}/competitions/serie-a/data',{'lang':'en'})
    (raw_root/'serie-a-current-catalog.json').write_bytes(cat_raw)
    cat_data=cat_obj.get('data') or {}
    players=player_array(cat_data)
    current_comp=(cat_data.get('slug') or 'serie-a')

    metadata_results=[]; metadata_errors=[]
    def fetch_meta(p):
        slug=p.get('slug'); pid=p.get('id')
        if not slug: return {'player':p,'error':'MISSING_SLUG'}
        url=f'{BASE}/players/serie-a/{slug}'
        try:
            obj,raw,final,status=request_json(url,{'lang':'en','fields':FIELDS_METADATA})
            path=metadata_root/f'{pid}-{slug}.json'; path.write_bytes(raw)
            return {'player':p,'obj':obj,'url':final,'status':status,'sha256':sha_bytes(raw),'path':path}
        except Exception as exc: return {'player':p,'url':url,'error':str(exc)}

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(fetch_meta,p) for p in players]
        for fut in as_completed(futs):
            r=fut.result()
            if r.get('error'): metadata_errors.append({'player_id':r['player'].get('id'),'player_name':r['player'].get('name'),'slug':r['player'].get('slug'),'url':r.get('url'),'error':r['error']})
            else: metadata_results.append(r)
    write_json(OUT/'metadata-errors.json',metadata_errors)

    player_rows=[]; season_ref_rows=[]; history_jobs=[]
    for r in metadata_results:
        p=r['player']; d=(r['obj'].get('data') or {}) if isinstance(r['obj'],dict) else {}
        current_profile_comp=d.get('competition') if isinstance(d.get('competition'),dict) else {'slug':'serie-a','name':'Serie A'}
        player_rows.append({
            'provider':'BIWENGER','current_competition':'Serie A','provider_player_id':p.get('id'),'player_name':d.get('name') or p.get('name'),'current_slug':p.get('slug'),'team_id':p.get('teamID'),'current_points':p.get('points'),'points_last_season':p.get('pointsLastSeason'),'metadata_source_url':r['url'],'metadata_source_sha256':r['sha256'],'metadata_source_local_path':str(r['path'].relative_to(OUT))
        })
        refs=d.get('seasons') or []
        if not isinstance(refs,list): refs=[]
        for idx,ref in enumerate(refs):
            if not isinstance(ref,dict): continue
            sid=str(ref.get('id') or '')
            if sid not in TARGET_SEASON_IDS: continue
            comp=ref.get('competition') if isinstance(ref.get('competition'),dict) else current_profile_comp
            pr=ref.get('player') if isinstance(ref.get('player'),dict) else {'id':p.get('id'),'slug':p.get('slug')}
            cslug=(comp or {}).get('slug')
            pslug=(pr or {}).get('slug') or p.get('slug')
            if not cslug or not pslug: continue
            row={
                'provider':'BIWENGER','current_seriea_player_id':p.get('id'),'current_player_name':d.get('name') or p.get('name'),'current_slug':p.get('slug'),'target_season':TARGET_SEASON_IDS[sid],'provider_season_id':sid,'provider_season_name':ref.get('name'),'provider_season_slug':ref.get('slug'),'competition_id':(comp or {}).get('id'),'competition_name':(comp or {}).get('name'),'competition_slug':cslug,'competition_class':competition_class(cslug),'historical_provider_player_id':(pr or {}).get('id'),'historical_player_slug':pslug,'games':ref.get('games'),'points_json':json.dumps(ref.get('points'),ensure_ascii=False,separators=(',',':')),'season_ref_index':idx,'season_ref_json':json.dumps(ref,ensure_ascii=False,default=str,separators=(',',':')),'metadata_source_sha256':r['sha256']
            }
            season_ref_rows.append(row); history_jobs.append(row)

    history_results=[]; history_errors=[]
    rawstats_keys=set(); report_keys=set(); event_types=set(); point_system_ids=set()
    def fetch_history(job):
        url=f"{BASE}/players/{job['competition_slug']}/{job['historical_player_slug']}"
        params={'lang':'en','fields':FIELDS_HISTORY,'season':job['provider_season_id']}
        try:
            obj,raw,final,status=request_json(url,params)
            comp_dir=mkdir(history_root/job['competition_slug']/job['target_season'])
            safe=f"{job['current_seriea_player_id']}-{job['historical_provider_player_id'] or 'na'}-{job['historical_player_slug']}.json"
            path=comp_dir/safe; path.write_bytes(raw)
            data=(obj.get('data') or {}) if isinstance(obj,dict) else {}
            reports=data.get('reports') or []
            if not isinstance(reports,list): reports=[]
            returned_comp=data.get('competition') if isinstance(data.get('competition'),dict) else {}
            return {'job':job,'url':final,'status':status,'sha256':sha_bytes(raw),'path':path,'reports':reports,'returned_comp':returned_comp,'data':data}
        except Exception as exc: return {'job':job,'url':url,'error':str(exc)}

    # Provider-friendly bounded concurrency. This is intentionally lower than the small probes.
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs=[ex.submit(fetch_history,j) for j in history_jobs]
        for fut in as_completed(futs):
            r=fut.result(); j=r['job']
            if r.get('error'):
                history_errors.append({**{k:j.get(k) for k in ['current_seriea_player_id','current_player_name','target_season','provider_season_id','competition_name','competition_slug','historical_provider_player_id','historical_player_slug']},'url':r.get('url'),'error':r['error']})
                continue
            reports=r['reports']; returned=r['returned_comp']
            mismatch=bool(returned.get('slug') and returned.get('slug')!=j['competition_slug'])
            nonempty=0
            for rep in reports:
                if not isinstance(rep,dict): continue
                nonempty+=1; report_keys.update(rep.keys())
                rs=rep.get('rawStats')
                if isinstance(rs,dict): rawstats_keys.update(rs.keys())
                pts=rep.get('points')
                if isinstance(pts,dict): point_system_ids.update(str(k) for k in pts.keys())
                ev=rep.get('events')
                if isinstance(ev,list):
                    for e in ev:
                        if isinstance(e,dict) and e.get('type') is not None: event_types.add(str(e.get('type')))
                elif isinstance(ev,dict):
                    if ev.get('type') is not None: event_types.add(str(ev.get('type')))
            history_results.append({
                **{k:j.get(k) for k in ['current_seriea_player_id','current_player_name','target_season','provider_season_id','provider_season_name','competition_id','competition_name','competition_slug','competition_class','historical_provider_player_id','historical_player_slug','games','points_json']},
                'reports_count':len(reports),'returned_competition_slug':returned.get('slug'),'competition_mismatch':mismatch,'source_url':r['url'],'source_sha256':r['sha256'],'source_local_path':str(r['path'].relative_to(OUT))
            })

    write_json(OUT/'history-errors.json',history_errors)
    write_csv(normalized/'current-seriea-players.csv',sorted(player_rows,key=lambda x:(str(x.get('player_name') or ''),str(x.get('provider_player_id') or ''))))
    write_csv(normalized/'player-season-references.csv',season_ref_rows)
    write_csv(normalized/'historical-report-index.csv',history_results)
    write_json(OUT/'field-inventory.json',{'report_keys':sorted(report_keys),'rawStats_keys':sorted(rawstats_keys),'event_type_ids_observed':sorted(event_types),'point_system_ids_observed':sorted(point_system_ids)})

    refs_with_games=[x for x in season_ref_rows if isinstance(x.get('games'),(int,float)) and x.get('games',0)>0]
    hist_by_key={(x['current_seriea_player_id'],x['provider_season_id'],x['competition_slug'],x['historical_player_slug']):x for x in history_results}
    matched_nonempty=0
    for x in refs_with_games:
        rr=hist_by_key.get((x['current_seriea_player_id'],x['provider_season_id'],x['competition_slug'],x['historical_player_slug']))
        if rr and rr.get('reports_count',0)>0: matched_nonempty+=1
    metadata_rate=(len(metadata_results)/len(players)) if players else 0.0
    nonempty_rate=(matched_nonempty/len(refs_with_games)) if refs_with_games else 0.0
    mismatches=sum(1 for x in history_results if x.get('competition_mismatch'))

    manifest={
        'schema':'NEXUS_BIWENGER_SERIEA_CROSSLEAGUE_HISTORY_V1',
        'status':'PASS' if players and metadata_rate>=0.95 and mismatches==0 else 'FAIL_VALIDATION',
        'capture_started':started,'capture_completed':now_iso(),
        'entry_catalog':{'url':cat_url,'status':cat_status,'sha256':sha_bytes(cat_raw),'players':len(players),'competition_slug':current_comp},
        'coverage':{'metadata_ok':len(metadata_results),'metadata_errors':len(metadata_errors),'metadata_success_rate':metadata_rate,'season_refs_in_window':len(season_ref_rows),'season_refs_with_games':len(refs_with_games),'historical_requests_ok':len(history_results),'historical_errors':len(history_errors),'refs_with_games_and_nonempty_reports':matched_nonempty,'nonempty_report_match_rate':nonempty_rate,'competition_mismatches':mismatches},
        'governance':{'history_window':list(TARGET_SEASON_IDS.values()),'cross_provider_normalization_performed':False,'missing_values_filled':False,'predictive_models_modified':False,'decision_layer_started':False,'season_refs_follow_provider_metadata_only':True,'event_type_semantics_interpreted':False},
    }
    write_json(OUT/'manifest.json',manifest)
    inventory=[]
    for path in sorted(p for p in OUT.rglob('*') if p.is_file()):
        if path.name=='file-inventory.json': continue
        inventory.append({'path':str(path.relative_to(OUT)),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    write_json(OUT/'file-inventory.json',inventory)
    print(json.dumps({'status':manifest['status'],'catalog_players':len(players),'metadata_ok':len(metadata_results),'season_refs':len(season_ref_rows),'history_ok':len(history_results),'history_errors':len(history_errors),'nonempty_rate':nonempty_rate,'competition_mismatches':mismatches,'files':len(inventory),'output':str(OUT)},ensure_ascii=False,indent=2))

if __name__=='__main__': main()
