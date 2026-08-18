from __future__ import annotations
import csv,hashlib,json,os,shutil,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from pathlib import Path
import requests
OUT=Path(os.environ.get('NEXUS_BIWENGER_UNIVERSE_OUT','/mnt/data/nexus-biwenger-universe-v1-1'))
BASE='https://cf.biwenger.com/api/v2'
CANDIDATES=['la-liga','premier-league','segunda-division','serie-a','ligue-1','primeira-liga','liga-mx','champions-league','copa-del-rey','world-cup','euro','club-world-cup','supercopa','copa-america','supercup','brasileirao','europa-league','conference-league','bundesliga','eredivisie','belgian-pro-league','ekstraklasa']
SCORES=[None]+list(range(1,13))
HEADERS={'User-Agent':'Mozilla/5.0 Chrome/151','Accept':'application/json, text/plain, */*','Referer':'https://biwenger.as.com/'}
def mkdir(p):p.mkdir(parents=True,exist_ok=True);return p
def now():return datetime.now(timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def dump(p,o):mkdir(p.parent);p.write_text(json.dumps(o,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def progress(phase,**kw):dump(OUT/'PROGRESS.json',{'schema':'NEXUS_BIWENGER_UNIVERSE_V1_1_PROGRESS','phase':phase,'updated':now(),**kw})
def req(url,params=None,attempts=4):
 last=None
 for i in range(attempts):
  try:
   r=requests.get(url,params=params or {},headers=HEADERS,timeout=(10,25));b=r.content
   try:o=r.json()
   except Exception:o=None
   if r.status_code==200 and isinstance(o,dict):return o,b,r.url,r.status_code
   last=RuntimeError(f'HTTP_{r.status_code} {r.url}')
   if r.status_code==429:time.sleep(min(12,1.5*2**i));continue
  except Exception as e:last=e
  time.sleep(min(4,.4*2**i))
 raise last or RuntimeError('request failed')
def players_of(obj):
 d=(obj.get('data') or {}) if isinstance(obj,dict) else {};p=d.get('players') or {}
 if isinstance(p,dict):return [x for x in p.values() if isinstance(x,dict)],d
 if isinstance(p,list):return [x for x in p if isinstance(x,dict)],d
 return [],d
def write_csv(p,rows):
 mkdir(p.parent)
 if not rows:p.write_text('',encoding='utf-8');return
 fs=[];seen=set()
 for r in rows:
  for k in r:
   if k not in seen:seen.add(k);fs.append(k)
 with p.open('w',newline='',encoding='utf-8') as f:
  w=csv.DictWriter(f,fieldnames=fs);w.writeheader();w.writerows(rows)
def catalog_one(slug,score):
 params={'lang':'en'}
 if score is not None:params['score']=score
 url=f'{BASE}/competitions/{slug}/data'
 try:
  obj,b,u,s=req(url,params);players,data=players_of(obj)
  return {'slug':slug,'score':score,'obj':obj,'bytes_raw':b,'url':u,'status':s,'players':players,'data':data}
 except Exception as e:return {'slug':slug,'score':score,'error':str(e)}
def main():
 if OUT.exists():shutil.rmtree(OUT)
 raw=mkdir(OUT/'raw');norm=mkdir(OUT/'normalized');started=now();progress('CATALOG_START',candidate_competitions=len(CANDIDATES),score_queries=len(SCORES),total_requests=len(CANDIDATES)*len(SCORES))
 # Same exact V1 22x13 discovery matrix, executed concurrently only.
 grid=[(slug,score) for slug in CANDIDATES for score in SCORES];results={};done=0
 with ThreadPoolExecutor(max_workers=8) as ex:
  futs={ex.submit(catalog_one,*x):x for x in grid}
  for fut in as_completed(futs):
   r=fut.result();results[(r['slug'],r['score'])]=r;done+=1
   if done%20==0 or done==len(grid):progress('CATALOG_RUNNING',completed=done,total=len(grid),errors=sum(1 for x in results.values() if x.get('error')))
 catalog_manifest=[];catalog_rows=[];identities={};valid_competitions=set();valid_modes={}
 # Deterministic original order retained regardless of completion order.
 for slug in CANDIDATES:
  modes=[]
  for score in SCORES:
   r=results[(slug,score)]
   if r.get('error'):
    catalog_manifest.append({'candidate_slug':slug,'score_query':score,'valid':False,'error':r['error']});continue
   players=r['players'];data=r['data'];b=r['bytes_raw'];valid=len(players)>0
   rec={'candidate_slug':slug,'score_query':score,'status':r['status'],'url':r['url'],'bytes':len(b),'sha256':sha(b),'valid':valid,'players':len(players),'data_slug':data.get('slug'),'competition_id':data.get('id'),'competition_name':data.get('name'),'scoreID':data.get('scoreID'),'season':data.get('season')}
   if valid:
    valid_competitions.add(slug);modes.append(score);d=mkdir(raw/'catalogs'/slug);fname=f"score-{'none' if score is None else score}.json";path=d/fname;path.write_bytes(b)
    for p in players:
     pid=p.get('id');key=(slug,str(pid));identities[key]={'competition_slug':slug,'provider_player_id':pid,'player_slug':p.get('slug'),'player_name':p.get('name')}
     catalog_rows.append({'provider':'BIWENGER','competition_candidate_slug':slug,'competition_name':data.get('name'),'competition_id':data.get('id'),'season_json':json.dumps(data.get('season'),ensure_ascii=False,default=str,separators=(',',':')),'score_query':score,'provider_scoreID':data.get('scoreID'),'provider_player_id':pid,'player_name':p.get('name'),'player_slug':p.get('slug'),'team_id':p.get('teamID'),'points':p.get('points'),'points_last_season':p.get('pointsLastSeason'),'source_url':r['url'],'source_sha256':sha(b),'source_local_path':str(path.relative_to(OUT)),'provider_fields_json':json.dumps(p,ensure_ascii=False,default=str,separators=(',',':'))})
   catalog_manifest.append(rec)
  valid_modes[slug]=modes
 dump(OUT/'catalog-manifest.json',catalog_manifest);write_csv(norm/'catalog-player-score-rows.csv',catalog_rows);progress('CATALOG_COMPLETE',valid_competitions=sorted(valid_competitions),identities=len(identities),catalog_score_rows=len(catalog_rows))
 metadata=[];metadata_errors=[];season_refs=[];meta_root=mkdir(raw/'player-metadata')
 def one(item):
  slug=item['competition_slug'];pslug=item.get('player_slug');pid=item.get('provider_player_id')
  if not pslug:return {'item':item,'error':'MISSING_PLAYER_SLUG'}
  params={'lang':'en','fields':'*,team,seasons,competition'};modes=valid_modes.get(slug) or []
  if modes and modes[0] is not None:params['score']=modes[0]
  url=f'{BASE}/players/{slug}/{pslug}'
  try:
   o,b,u,s=req(url,params);d=(o.get('data') or {}) if isinstance(o,dict) else {};path=mkdir(meta_root/slug)/f'{pid}-{pslug}.json';path.write_bytes(b);return {'item':item,'data':d,'url':u,'status':s,'sha256':sha(b),'path':path}
  except Exception as e:return {'item':item,'url':url,'error':str(e)}
 items=list(identities.values());done=0
 with ThreadPoolExecutor(max_workers=12) as ex:
  futs=[ex.submit(one,x) for x in items]
  for fut in as_completed(futs):
   r=fut.result();it=r['item'];done+=1
   if r.get('error'):metadata_errors.append({**it,'url':r.get('url'),'error':r['error']})
   else:
    d=r['data'];comp=d.get('competition') if isinstance(d.get('competition'),dict) else {}
    metadata.append({'provider':'BIWENGER','competition_candidate_slug':it['competition_slug'],'returned_competition_slug':comp.get('slug'),'provider_player_id':it['provider_player_id'],'player_name':d.get('name') or it.get('player_name'),'player_slug':it.get('player_slug'),'team_id':(d.get('team') or {}).get('id') if isinstance(d.get('team'),dict) else None,'source_url':r['url'],'source_sha256':r['sha256'],'source_local_path':str(r['path'].relative_to(OUT))})
    refs=d.get('seasons') or []
    if isinstance(refs,list):
     for ref in refs:
      if not isinstance(ref,dict):continue
      c=ref.get('competition') if isinstance(ref.get('competition'),dict) else {};hp=ref.get('player') if isinstance(ref.get('player'),dict) else {}
      season_refs.append({'provider':'BIWENGER','current_competition_slug':it['competition_slug'],'current_provider_player_id':it['provider_player_id'],'current_player_name':d.get('name') or it.get('player_name'),'provider_season_id':ref.get('id'),'provider_season_name':ref.get('name'),'provider_season_slug':ref.get('slug'),'games':ref.get('games'),'points_json':json.dumps(ref.get('points'),ensure_ascii=False,default=str,separators=(',',':')),'historical_competition_id':c.get('id'),'historical_competition_name':c.get('name'),'historical_competition_slug':c.get('slug'),'historical_provider_player_id':hp.get('id'),'historical_player_slug':hp.get('slug'),'season_ref_json':json.dumps(ref,ensure_ascii=False,default=str,separators=(',',':')),'metadata_source_sha256':r['sha256']})
   if done%50==0 or done==len(items):progress('METADATA_RUNNING',completed=done,total=len(items),ok=len(metadata),errors=len(metadata_errors),season_references=len(season_refs))
 write_csv(norm/'player-metadata-index.csv',metadata);write_csv(norm/'player-season-references.csv',season_refs);dump(OUT/'metadata-errors.json',metadata_errors)
 rate=len(metadata)/len(identities) if identities else 0
 manifest={'schema':'NEXUS_BIWENGER_UNIVERSE_V1','execution_profile':'V1_1_BOUNDED_CONCURRENT_SAME_PROTOCOL','status':'PASS' if len(valid_competitions)>=5 and rate>=0.95 else 'FAIL_VALIDATION','capture_started':started,'capture_completed':now(),'coverage':{'candidate_competitions':len(CANDIDATES),'valid_competitions':sorted(valid_competitions),'valid_competition_count':len(valid_competitions),'catalog_score_rows':len(catalog_rows),'unique_competition_player_identities':len(identities),'metadata_ok':len(metadata),'metadata_errors':len(metadata_errors),'metadata_success_rate':rate,'season_references':len(season_refs)},'valid_score_queries_by_competition':valid_modes,'governance':{'same_protocol_candidate_competitions':True,'same_protocol_score_queries':True,'same_protocol_metadata_fields':True,'cross_score_mode_normalization_performed':False,'cross_competition_normalization_performed':False,'missing_values_filled':False,'predictive_models_modified':False,'decision_layer_started':False,'history_reports_downloaded':False}}
 dump(OUT/'manifest.json',manifest)
 inv=[]
 for p in sorted(x for x in OUT.rglob('*') if x.is_file()):
  if p.name=='file-inventory.json':continue
  inv.append({'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
 dump(OUT/'file-inventory.json',inv);progress('COMPLETE',status=manifest['status'],coverage=manifest['coverage']);print(json.dumps({'status':manifest['status'],'coverage':manifest['coverage'],'valid_scores':valid_modes,'files':len(inv)},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
