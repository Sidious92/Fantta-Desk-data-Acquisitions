from __future__ import annotations
import csv, hashlib, json, os, shutil, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT=Path(os.environ.get('NEXUS_FANTASYVOETBAL_OUT','/mnt/data/nexus-fantasyvoetbal-eredivisie-v1'))
BASE='https://fantasy.espngoal.nl/api'
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept':'application/json, text/plain, */*','Referer':'https://fantasy.espngoal.nl/'}

def now(): return datetime.now(timezone.utc).isoformat()
def mkdir(p): p.mkdir(parents=True,exist_ok=True); return p
def sha(b): return hashlib.sha256(b).hexdigest()
def dump(p,o): mkdir(p.parent); p.write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def req(path,attempts=4):
    u=BASE+'/'+path.lstrip('/')
    last=None
    for i in range(attempts):
        try:
            r=requests.get(u,headers=HEADERS,timeout=35)
            b=r.content
            if r.status_code==200:
                return r.json(),b,r.url,r.status_code
            last=RuntimeError(f'HTTP_{r.status_code} {r.url} {r.text[:200]!r}')
        except Exception as e: last=e
        time.sleep(min(2,0.3*2**i))
    raise last or RuntimeError('request failed')
def write_csv(p,rows):
    mkdir(p.parent)
    if not rows: p.write_text('',encoding='utf-8'); return
    fields=[]; seen=set()
    for r in rows:
        for k in r:
            if k not in seen: seen.add(k); fields.append(k)
    with p.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
def flat_keys(rows):
    s=set()
    for r in rows:
        if isinstance(r,dict): s.update(r.keys())
    return sorted(s)

def main():
    if OUT.exists(): shutil.rmtree(OUT)
    raw=mkdir(OUT/'raw'); summaries=mkdir(raw/'element-summaries'); norm=mkdir(OUT/'normalized')
    started=now()
    bootstrap,bb,bu,bs=req('bootstrap-static/')
    (raw/'bootstrap-static.json').write_bytes(bb)
    try:
        fixtures,fb,fu,fs=req('fixtures/')
        (raw/'fixtures.json').write_bytes(fb)
    except Exception as exc:
        fixtures=[]; fb=b''; fu=BASE+'/fixtures/'; fs=None
        dump(OUT/'fixtures-error.json',{'error':str(exc)})
    elements=bootstrap.get('elements') or [] if isinstance(bootstrap,dict) else []
    teams=bootstrap.get('teams') or [] if isinstance(bootstrap,dict) else []
    team_by_id={x.get('id'):x for x in teams if isinstance(x,dict)}
    player_rows=[]
    for e in elements:
        if not isinstance(e,dict): continue
        t=team_by_id.get(e.get('team')) or {}
        player_rows.append({'provider':'ESPN_FANTASY_VOETBAL','competition':'Eredivisie','provider_player_id':e.get('id'),'first_name':e.get('first_name'),'second_name':e.get('second_name'),'web_name':e.get('web_name'),'team_id':e.get('team'),'team_name':t.get('name'),'element_type':e.get('element_type'),'total_points':e.get('total_points'),'event_points':e.get('event_points'),'minutes':e.get('minutes'),'goals_scored':e.get('goals_scored'),'assists':e.get('assists'),'yellow_cards':e.get('yellow_cards'),'red_cards':e.get('red_cards'),'own_goals':e.get('own_goals'),'penalties_missed':e.get('penalties_missed'),'penalties_saved':e.get('penalties_saved'),'clean_sheets':e.get('clean_sheets'),'goals_conceded':e.get('goals_conceded'),'saves':e.get('saves'),'starts':e.get('starts'),'form':e.get('form'),'now_cost':e.get('now_cost'),'provider_fields_json':json.dumps(e,ensure_ascii=False,default=str,separators=(',',':'))})

    results=[]; errors=[]
    def fetch_summary(e):
        pid=e.get('id')
        try:
            obj,b,u,s=req(f'element-summary/{pid}/')
            path=summaries/f'{pid}.json'; path.write_bytes(b)
            return {'id':pid,'obj':obj,'url':u,'status':s,'sha256':sha(b),'path':path}
        except Exception as exc: return {'id':pid,'error':str(exc)}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(fetch_summary,e) for e in elements if isinstance(e,dict) and e.get('id') is not None]
        for fut in as_completed(futs):
            r=fut.result()
            if r.get('error'): errors.append(r)
            else: results.append(r)
    dump(OUT/'element-summary-errors.json',errors)

    current_rows=[]; past_rows=[]; summary_fields={'fixtures':set(),'history':set(),'history_past':set()}
    name_by_id={r['provider_player_id']:r for r in player_rows}
    for r in results:
        obj=r['obj'] if isinstance(r['obj'],dict) else {}
        meta=name_by_id.get(r['id']) or {}
        for section,target in [('history',current_rows),('history_past',past_rows)]:
            arr=obj.get(section) or []
            if not isinstance(arr,list): continue
            for x in arr:
                if not isinstance(x,dict): continue
                summary_fields[section].update(x.keys())
                target.append({'provider':'ESPN_FANTASY_VOETBAL','competition':'Eredivisie','provider_player_id':r['id'],'web_name':meta.get('web_name'),'team_name':meta.get('team_name'),'source_url':r['url'],'source_sha256':r['sha256'],'source_local_path':str(r['path'].relative_to(OUT)),'provider_fields_json':json.dumps(x,ensure_ascii=False,default=str,separators=(',',':')),...x})
        arr=obj.get('fixtures') or []
        if isinstance(arr,list):
            for x in arr:
                if isinstance(x,dict): summary_fields['fixtures'].update(x.keys())

    write_csv(norm/'players-current.csv',player_rows)
    write_csv(norm/'player-history-current-season.csv',current_rows)
    write_csv(norm/'player-history-past-seasons.csv',past_rows)
    dump(OUT/'field-inventory.json',{
        'bootstrap_top_level':sorted(bootstrap.keys()) if isinstance(bootstrap,dict) else [],
        'elements':flat_keys(elements), 'teams':flat_keys(teams),
        'element_summary_history':sorted(summary_fields['history']),
        'element_summary_history_past':sorted(summary_fields['history_past']),
        'element_summary_fixtures':sorted(summary_fields['fixtures']),
    })
    rate=len(results)/len(elements) if elements else 0
    manifest={'schema':'NEXUS_FANTASYVOETBAL_EREDIVISIE_V1','status':'PASS' if elements and rate>=0.95 else 'FAIL_VALIDATION','capture_started':started,'capture_completed':now(),'bootstrap':{'url':bu,'status':bs,'sha256':sha(bb),'players':len(elements),'teams':len(teams)},'fixtures':{'url':fu,'status':fs,'sha256':sha(fb) if fb else None,'rows':len(fixtures) if isinstance(fixtures,list) else None},'coverage':{'summary_ok':len(results),'summary_errors':len(errors),'summary_success_rate':rate,'current_history_rows':len(current_rows),'past_history_rows':len(past_rows)},'governance':{'provider_native_fields_preserved':True,'cross_provider_normalization_performed':False,'missing_values_filled':False,'predictive_models_modified':False,'decision_layer_started':False}}
    dump(OUT/'manifest.json',manifest)
    inventory=[]
    for p in sorted(x for x in OUT.rglob('*') if x.is_file()):
        if p.name=='file-inventory.json': continue
        inventory.append({'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    dump(OUT/'file-inventory.json',inventory)
    print(json.dumps({'status':manifest['status'],'players':len(elements),'teams':len(teams),'summary_ok':len(results),'current_history_rows':len(current_rows),'past_history_rows':len(past_rows),'files':len(inventory)},indent=2))
if __name__=='__main__': main()
