from __future__ import annotations

import csv, hashlib, json, os, shutil, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

OUT=Path(os.environ.get('NEXUS_FANTASY_EFL_OUT','/mnt/data/nexus-fantasy-efl-public-json-v1'))
BASE='https://fantasy.efl.com/json/'
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept':'application/json, text/plain, */*','Referer':'https://fantasy.efl.com/'}
STATIC={
    'countries':'countries.json',
    'rounds':'fantasy/rounds.json',
    'tips_rounds':'fantasy/creatives/rounds.json',
    'players':'fantasy/players.json',
    'squads':'fantasy/squads.json',
    'competitions':'fantasy/competitions.json',
    'checksums':'checksums.json',
    'months':'fantasy/months.json',
    'off_season':'off_season.json',
    'play_off_landing':'fantasy/play_off_landing.json',
    'news':'fantasy/news.json',
    'stats_page':'fantasy/stats_page.json',
    'ladders':'fantasy/ladders.json',
    'seasons':'fantasy/seasons.json',
}

def mkdir(p): p.mkdir(parents=True,exist_ok=True); return p
def now(): return datetime.now(timezone.utc).isoformat()
def sha(b): return hashlib.sha256(b).hexdigest()
def dump(p,o): mkdir(p.parent); p.write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def req(path,attempts=4):
    url=BASE+path.lstrip('/');last=None
    for i in range(attempts):
        try:
            r=requests.get(url,headers=HEADERS,timeout=35);b=r.content
            if r.status_code==200:
                return r.json(),b,r.url,r.status_code
            last=RuntimeError(f'HTTP_{r.status_code} {r.url} {r.text[:200]!r}')
        except Exception as exc:last=exc
        time.sleep(min(2.0,0.3*(2**i)))
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
def pick_list(obj):
    if isinstance(obj,list):return [x for x in obj if isinstance(x,dict)]
    if isinstance(obj,dict):
        for key in ['data','players','squads','competitions','rounds','results','items']:
            v=obj.get(key)
            if isinstance(v,list) and all(isinstance(x,dict) for x in v):return v
            if isinstance(v,dict):
                arr=[x for x in v.values() if isinstance(x,dict)]
                if arr:return arr
    return []
def ident(row):
    if not isinstance(row,dict):return None
    for k in ['id','playerId','player_id']:
        v=row.get(k)
        if v is not None:return str(v)
    return None
def scalar(row): return {k:v for k,v in row.items() if not isinstance(v,(dict,list))}

def main():
    if OUT.exists():shutil.rmtree(OUT)
    raw=mkdir(OUT/'raw');norm=mkdir(OUT/'normalized');started=now()
    payloads={};surface_manifest={};errors=[]
    for name,path in STATIC.items():
        try:
            obj,b,u,s=req(path);payloads[name]=obj;p=raw/path;mkdir(p.parent);p.write_bytes(b)
            surface_manifest[name]={'path':path,'url':u,'status':s,'bytes':len(b),'sha256':sha(b),'json_type':type(obj).__name__,'rows':len(obj) if isinstance(obj,(list,dict)) else None,'local_path':str(p.relative_to(OUT))}
        except Exception as exc:
            surface_manifest[name]={'path':path,'error':str(exc)};errors.append({'surface':name,'path':path,'error':str(exc)})
    players=pick_list(payloads.get('players'));squads=pick_list(payloads.get('squads'));competitions=pick_list(payloads.get('competitions'));rounds=pick_list(payloads.get('rounds'));seasons=pick_list(payloads.get('seasons'))
    squad_map={str(x.get('id')):x for x in squads if x.get('id') is not None}
    comp_map={str(x.get('id')):x for x in competitions if x.get('id') is not None}
    player_rows=[]
    for p in players:
        pid=ident(p);sid=p.get('squadId') or p.get('squad_id') or p.get('teamId');squad=squad_map.get(str(sid)) or {}
        cid=p.get('competitionId') or squad.get('competitionId');comp=comp_map.get(str(cid)) or {}
        player_rows.append({'provider':'FANTASY_EFL','provider_player_id':pid,'competition_id':cid,'competition_name':comp.get('name'),'competition_code':comp.get('code') or comp.get('short') or comp.get('feed'),'squad_id':sid,'squad_name':squad.get('name'),'player_name':' '.join(str(x or '') for x in [p.get('firstName'),p.get('lastName')]).strip() or p.get('name'),'position':p.get('position'),'total_points':p.get('totalPoints'),'round_points':p.get('roundPoints'),'average_points':p.get('averagePoints'),'appearances':p.get('appearances'),'goals_scored':p.get('goalsScored'),'assists':p.get('assists'),'key_passes':p.get('keyPasses'),'shots_on_target':p.get('shotsOnTarget'),'clean_sheets':p.get('cleanSheets'),'clearances':p.get('clearances'),'blocks':p.get('blocks'),'tackles':p.get('tackles'),'interceptions':p.get('interceptions'),'saves':p.get('saves'),'provider_fields_json':json.dumps(p,ensure_ascii=False,default=str,separators=(',',':')),**scalar(p)})
    write_csv(norm/'players.csv',player_rows);write_csv(norm/'squads.csv',[{'provider':'FANTASY_EFL',**scalar(x),'provider_fields_json':json.dumps(x,ensure_ascii=False,default=str,separators=(',',':'))} for x in squads]);write_csv(norm/'competitions.csv',[{'provider':'FANTASY_EFL',**scalar(x),'provider_fields_json':json.dumps(x,ensure_ascii=False,default=str,separators=(',',':'))} for x in competitions]);write_csv(norm/'seasons.csv',[{'provider':'FANTASY_EFL',**scalar(x),'provider_fields_json':json.dumps(x,ensure_ascii=False,default=str,separators=(',',':'))} for x in seasons])

    profiles=mkdir(raw/'fantasy/player_profiles');profile_rows=[];profile_result_rows=[];profile_errors=[];profile_fields=set()
    def one(p):
        pid=ident(p)
        if pid is None:return {'pid':None,'error':'MISSING_ID'}
        path=f'fantasy/player_profiles/{pid}.json'
        try:
            obj,b,u,s=req(path);q=profiles/f'{pid}.json';q.write_bytes(b);return {'pid':pid,'obj':obj,'url':u,'sha256':sha(b),'path':q}
        except Exception as exc:return {'pid':pid,'error':str(exc)}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(one,p) for p in players]
        for fut in as_completed(futs):
            r=fut.result();pid=r['pid']
            if r.get('error'):profile_errors.append({'provider_player_id':pid,'error':r['error']});continue
            obj=r['obj'];profile_rows.append({'provider':'FANTASY_EFL','provider_player_id':pid,'source_url':r['url'],'source_sha256':r['sha256'],'source_local_path':str(r['path'].relative_to(OUT)),'provider_profile_json':json.dumps(obj,ensure_ascii=False,default=str,separators=(',',':'))})
            if isinstance(obj,dict):
                profile_fields.update(obj.keys());arr=obj.get('results')
                if isinstance(arr,list):
                    for x in arr:
                        if isinstance(x,dict):profile_result_rows.append({'provider':'FANTASY_EFL','provider_player_id':pid,'source_sha256':r['sha256'],'provider_fields_json':json.dumps(x,ensure_ascii=False,default=str,separators=(',',':')),**scalar(x)})
    write_csv(norm/'player-profile-index.csv',profile_rows);write_csv(norm/'player-profile-results.csv',profile_result_rows);dump(OUT/'player-profile-errors.json',profile_errors)

    # Read-only round live-score JSON for discovered round ids.
    live_rows=[];live_errors=[];live_root=mkdir(raw/'fantasy/live_scores')
    round_ids=[str(x.get('id')) for x in rounds if x.get('id') is not None]
    def live(rid):
        try:
            obj,b,u,s=req(f'fantasy/live_scores/{rid}.json');q=live_root/f'{rid}.json';q.write_bytes(b);return {'round_id':rid,'obj':obj,'url':u,'sha256':sha(b),'path':q}
        except Exception as exc:return {'round_id':rid,'error':str(exc)}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs=[ex.submit(live,rid) for rid in round_ids]
        for fut in as_completed(futs):
            r=fut.result()
            if r.get('error'):live_errors.append({'round_id':r['round_id'],'error':r['error']});continue
            live_rows.append({'provider':'FANTASY_EFL','round_id':r['round_id'],'source_url':r['url'],'source_sha256':r['sha256'],'source_local_path':str(r['path'].relative_to(OUT)),'provider_fields_json':json.dumps(r['obj'],ensure_ascii=False,default=str,separators=(',',':'))})
    write_csv(norm/'live-score-index.csv',live_rows);dump(OUT/'live-score-errors.json',live_errors)

    comp_codes=set()
    for c in competitions:
        for k in ['code','short','feed','slug']:
            v=c.get(k)
            if v is not None:comp_codes.add(str(v))
    rate=len(profile_rows)/len(players) if players else 0
    manifest={'schema':'NEXUS_FANTASY_EFL_PUBLIC_JSON_V1','status':'PASS' if len(players)>100 and rate>=0.95 else 'FAIL_VALIDATION','capture_started':started,'capture_completed':now(),'public_json_base':BASE,'coverage':{'players':len(players),'squads':len(squads),'competitions':len(competitions),'seasons':len(seasons),'rounds':len(rounds),'player_profiles_ok':len(profile_rows),'player_profile_errors':len(profile_errors),'player_profile_success_rate':rate,'player_profile_result_rows':len(profile_result_rows),'live_rounds_ok':len(live_rows),'live_round_errors':len(live_errors)},'competition_codes_observed':sorted(comp_codes),'profile_top_level_fields':sorted(profile_fields),'surfaces':surface_manifest,'errors':errors,'governance':{'authenticated_api_accessed':False,'commercial_genius_api_accessed':False,'cross_provider_normalization_performed':False,'missing_values_filled':False,'predictive_models_modified':False,'decision_layer_started':False}}
    dump(OUT/'manifest.json',manifest)
    inv=[]
    for p in sorted(x for x in OUT.rglob('*') if x.is_file()):
        if p.name=='file-inventory.json':continue
        inv.append({'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    dump(OUT/'file-inventory.json',inv);print(json.dumps({'status':manifest['status'],'coverage':manifest['coverage'],'competition_codes':manifest['competition_codes_observed'],'files':len(inv)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
