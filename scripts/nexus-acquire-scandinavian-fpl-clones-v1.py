from __future__ import annotations
import csv, hashlib, json, os, shutil, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import requests

OUT=Path(os.environ.get('NEXUS_SCANDINAVIA_FANTASY_OUT','/mnt/data/nexus-scandinavian-fpl-clones-v1'))
PROVIDERS=[
    {'key':'ELITESERIEN','name':'Fantasy Eliteserien','competition':'Eliteserien','base':'https://en.fantasy.eliteserien.no/api/'},
    {'key':'ALLSVENSKAN','name':'Allsvenskan Fantasy','competition':'Allsvenskan','base':'https://en.fantasy.allsvenskan.se/api/'},
]
HEADERS={'User-Agent':'Mozilla/5.0 Chrome/151','Accept':'application/json, text/plain, */*'}

def mkdir(p): p.mkdir(parents=True,exist_ok=True); return p
def now(): return datetime.now(timezone.utc).isoformat()
def sha(b): return hashlib.sha256(b).hexdigest()
def dump(p,o): mkdir(p.parent); p.write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def req(base,path,attempts=4):
    u=base+path.lstrip('/'); last=None
    for i in range(attempts):
        try:
            r=requests.get(u,headers=HEADERS,timeout=35); b=r.content
            if r.status_code==200: return r.json(),b,r.url,r.status_code
            last=RuntimeError(f'HTTP_{r.status_code} {r.url}')
        except Exception as e: last=e
        time.sleep(min(2,0.3*2**i))
    raise last or RuntimeError('request failed')
def write_csv(p,rows):
    mkdir(p.parent)
    if not rows: p.write_text('',encoding='utf-8'); return
    fs=[]; seen=set()
    for r in rows:
        for k in r:
            if k not in seen: seen.add(k); fs.append(k)
    with p.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=fs); w.writeheader(); w.writerows(rows)
def flatten_history(provider,element,team,section,row,url,digest,local):
    return {'provider':provider['key'],'provider_name':provider['name'],'competition':provider['competition'],'provider_player_id':element.get('id'),'player_code':element.get('code'),'web_name':element.get('web_name'),'team_id':element.get('team'),'team_name':team.get('name'),'history_section':section,'source_url':url,'source_sha256':digest,'source_local_path':local,'provider_fields_json':json.dumps(row,ensure_ascii=False,default=str,separators=(',',':')),**row}
def acquire(p):
    root=mkdir(OUT/p['key'].lower()); raw=mkdir(root/'raw'); sums=mkdir(raw/'element-summaries'); norm=mkdir(root/'normalized')
    boot,bb,bu,bs=req(p['base'],'bootstrap-static/'); (raw/'bootstrap-static.json').write_bytes(bb)
    try:
        fix,fb,fu,fs=req(p['base'],'fixtures/'); (raw/'fixtures.json').write_bytes(fb)
    except Exception as exc:
        fix=[]; fb=b''; fu=p['base']+'fixtures/'; fs=None; dump(root/'fixtures-error.json',{'error':str(exc)})
    for name,path in [('regions','regions/'),('dream-team','dream-team/')]:
        try:
            o,b,u,s=req(p['base'],path); (raw/f'{name}.json').write_bytes(b)
        except Exception as exc: dump(root/f'{name}-error.json',{'error':str(exc)})
    elements=boot.get('elements') or []; teams=boot.get('teams') or []; tmap={t.get('id'):t for t in teams if isinstance(t,dict)}
    players=[]
    for e in elements:
        if not isinstance(e,dict): continue
        t=tmap.get(e.get('team')) or {}
        players.append({'provider':p['key'],'provider_name':p['name'],'competition':p['competition'],'provider_player_id':e.get('id'),'player_code':e.get('code'),'first_name':e.get('first_name'),'second_name':e.get('second_name'),'web_name':e.get('web_name'),'team_id':e.get('team'),'team_name':t.get('name'),'element_type':e.get('element_type'),'total_points':e.get('total_points'),'minutes':e.get('minutes'),'goals_scored':e.get('goals_scored'),'assists':e.get('assists'),'yellow_cards':e.get('yellow_cards'),'red_cards':e.get('red_cards'),'own_goals':e.get('own_goals'),'penalties_missed':e.get('penalties_missed'),'penalties_saved':e.get('penalties_saved'),'clean_sheets':e.get('clean_sheets'),'goals_conceded':e.get('goals_conceded'),'saves':e.get('saves'),'starts':e.get('starts'),'provider_fields_json':json.dumps(e,ensure_ascii=False,default=str,separators=(',',':'))})
    results=[]; errors=[]
    def one(e):
        pid=e.get('id')
        try:
            o,b,u,s=req(p['base'],f'element-summary/{pid}/'); path=sums/f'{pid}.json'; path.write_bytes(b); return {'element':e,'obj':o,'url':u,'sha':sha(b),'path':path}
        except Exception as exc: return {'element':e,'error':str(exc)}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs=[ex.submit(one,e) for e in elements if isinstance(e,dict)]
        for fut in as_completed(futs):
            r=fut.result(); (errors if r.get('error') else results).append(r)
    current=[]; past=[]
    for r in results:
        e=r['element']; t=tmap.get(e.get('team')) or {}; o=r['obj'] if isinstance(r['obj'],dict) else {}
        for sec,target in [('history',current),('history_past',past)]:
            arr=o.get(sec) or []
            if isinstance(arr,list):
                for row in arr:
                    if isinstance(row,dict): target.append(flatten_history(p,e,t,sec,row,r['url'],r['sha'],str(r['path'].relative_to(root))))
    write_csv(norm/'players-current.csv',players); write_csv(norm/'history-current.csv',current); write_csv(norm/'history-past.csv',past); dump(root/'element-summary-errors.json',errors)
    rate=len(results)/len(elements) if elements else 0
    manifest={'provider':p['key'],'provider_name':p['name'],'competition':p['competition'],'base_api':p['base'],'bootstrap_players':len(elements),'teams':len(teams),'summary_ok':len(results),'summary_errors':len(errors),'summary_success_rate':rate,'current_history_rows':len(current),'past_history_rows':len(past),'status':'PASS' if elements and rate>=0.95 else 'FAIL_VALIDATION','bootstrap_sha256':sha(bb),'fixtures_sha256':sha(fb) if fb else None}
    dump(root/'manifest.json',manifest); return manifest
def main():
    if OUT.exists(): shutil.rmtree(OUT)
    mkdir(OUT); started=now(); manifests=[acquire(p) for p in PROVIDERS]
    status='PASS' if all(m['status']=='PASS' for m in manifests) else 'FAIL_VALIDATION'
    master={'schema':'NEXUS_SCANDINAVIAN_FPL_CLONES_V1','status':status,'capture_started':started,'capture_completed':now(),'providers':manifests,'governance':{'cross_provider_normalization_performed':False,'missing_values_filled':False,'predictive_models_modified':False,'decision_layer_started':False}}
    dump(OUT/'manifest.json',master)
    inv=[]
    for p in sorted(x for x in OUT.rglob('*') if x.is_file()):
        if p.name=='file-inventory.json': continue
        inv.append({'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    dump(OUT/'file-inventory.json',inv); print(json.dumps({'status':status,'providers':manifests,'files':len(inv)},indent=2))
if __name__=='__main__': main()
