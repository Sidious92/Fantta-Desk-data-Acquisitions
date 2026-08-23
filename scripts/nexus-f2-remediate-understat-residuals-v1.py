#!/usr/bin/env python3
import argparse,csv,gzip,hashlib,io,json,re,time,urllib.request
from collections import defaultdict,Counter
from datetime import datetime,timezone
from pathlib import Path

US_COMMIT='768b7ca0b977a5e6b4b429c7b0cf750e8269f2fc'
US_SHA256='b78fad5f01844a0fdab0d89474dafba9b86c586d2f0ce88f0ce2c9af70d2bc64'
US_URL=f'https://raw.githubusercontent.com/vibedatascience/understat_players_aggregated/{US_COMMIT}/understat_players_aggregated_2014_2024.csv'
MATCH_API='https://understat.com/getMatchData/{match_id}'
UA='Mozilla/5.0 (compatible; FantaNexus-F2-Residual-Remediation/1.0)'
LEAGUES={'Serie_A','EPL','La_Liga','Bundesliga','Ligue_1','RFPL'}
FIELDS=['games','time','goals','npg','assists','shots','key_passes']
EXPECTED_PLAYERS=2048
EXPECTED_REFS=8399
SOURCE_RUN_ID='32663544437'
SOURCE_ARTIFACT_SHA256='bcb9237887828e60fe2b862b7c18e4139266948bf2ba796885ed839f95ccc01f'
SOURCE_PACKAGE_SHA256='00a60a8a8b645e9bf171a354a4adb547c85b70085974596b093ea3dd7d5b329c'

def H(b): return hashlib.sha256(b).hexdigest()
def canon(o): return json.dumps(o,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def fetch(url,ajax=False):
    h={'User-Agent':UA,'Accept':'application/json,text/plain,*/*','Accept-Encoding':'gzip'}
    if ajax: h['X-Requested-With']='XMLHttpRequest'
    req=urllib.request.Request(url,headers=h)
    with urllib.request.urlopen(req,timeout=90) as r:
        wire=r.read(); enc=str(r.headers.get('Content-Encoding') or '').lower()
        if r.status!=200: raise RuntimeError(f'HTTP_{r.status}:{url}')
        raw=gzip.decompress(wire) if wire.startswith(b'\x1f\x8b') or 'gzip' in enc else wire
        return wire,raw,enc

def season(v):
    s=str(v or '').strip(); m=re.fullmatch(r'(\d{4})/(\d{2})',s)
    if m:
        y=int(m.group(1)); yy=int(m.group(2))
        if yy!=(y+1)%100: raise ValueError(s)
        return s
    if re.fullmatch(r'\d{4}',s):
        y=int(s); return f'{y}/{(y+1)%100:02d}'
    raise ValueError(s)

def iv(v,field,pid,sea):
    f=float(v); i=int(f)
    if f!=i: raise RuntimeError(f'NON_INTEGER:{pid}:{sea}:{field}:{v!r}')
    return i

def clubs(text): return [x.strip() for x in str(text or '').split(',') if x.strip()]
def write_json(path,obj):
    raw=(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode(); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw); return {'path':str(path),'bytes':len(raw),'sha256':H(raw)}
def write_jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='\n') as f:
        for r in rows: f.write(canon(r)+'\n')
    raw=path.read_bytes(); return {'path':str(path),'bytes':len(raw),'rows':len(rows),'sha256':H(raw)}

def roster_side(payload,pid):
    ros=payload.get('rosters') if isinstance(payload,dict) else None
    if not isinstance(ros,dict): return None,'ROSTER_SHAPE_INVALID'
    hits=[]
    for side in ('h','a'):
        side_obj=ros.get(side)
        if not isinstance(side_obj,dict): continue
        for row in side_obj.values():
            if isinstance(row,dict) and str(row.get('player_id') or '')==str(pid): hits.append(side)
    hits=sorted(set(hits))
    return (hits[0],None) if len(hits)==1 else (None,f'PLAYER_ROSTER_SIDE_COUNT_{len(hits)}')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input-root',required=True); ap.add_argument('--output-root',required=True); ap.add_argument('--delay',type=float,default=.35); args=ap.parse_args()
    root=Path(args.input_root); out=Path(args.output_root); out.mkdir(parents=True,exist_ok=True); roster_raw=out/'match-roster-raw'; roster_raw.mkdir(exist_ok=True)
    failures=[]
    index_paths=sorted(root.rglob('player-index.json')); reg_paths=sorted(root.rglob('SHARD_REGISTRY.json'))
    if len(index_paths)!=8 or len(reg_paths)!=8: failures.append({'code':'SOURCE_SHARD_SET_INCOMPLETE','indexFiles':len(index_paths),'registryFiles':len(reg_paths)})
    pid_person={}; api_files={}
    for ip in index_paths:
        for row in json.loads(ip.read_text(encoding='utf-8')):
            pid=str(row['playerId']); pk=row['personKey']
            if pid in pid_person and pid_person[pid]!=pk: failures.append({'code':'SOURCE_PLAYER_PERSON_CONFLICT','playerId':pid})
            pid_person[pid]=pk
            candidates=list(ip.parent.glob(f'raw/player-{pid}-api.json'))
            if len(candidates)!=1: failures.append({'code':'SOURCE_PLAYER_API_FILE_COUNT','playerId':pid,'count':len(candidates)})
            elif pid not in api_files: api_files[pid]=candidates[0]
    if len(pid_person)!=EXPECTED_PLAYERS: failures.append({'code':'SOURCE_PLAYER_COUNT_MISMATCH','expected':EXPECTED_PLAYERS,'observed':len(pid_person)})
    _,us_raw,_=fetch(US_URL)
    if H(us_raw)!=US_SHA256: raise SystemExit('PINNED_AGGREGATE_HASH_MISMATCH')
    refs=defaultdict(list); refs_by_ps=defaultdict(list)
    for r in csv.DictReader(io.StringIO(us_raw.decode('utf-8-sig'))):
        pid=str(r.get('id') or ''); lg=str(r.get('league') or '')
        if pid not in pid_person or lg not in LEAGUES: continue
        sea=season(r.get('season')); rr={**r,'_season':sea,'_league':lg,'_clubs':clubs(r.get('team_title'))}; refs[(pid,sea,lg)].append(rr); refs_by_ps[(pid,sea)].append(rr)
    if len(refs)!=EXPECTED_REFS: failures.append({'code':'SOURCE_REFERENCE_COUNT_MISMATCH','expected':EXPECTED_REFS,'observed':len(refs)})

    player_rows={}; duplicate_audit=[]; ambiguous_requests={}
    for pid in sorted(pid_person,key=lambda x:(int(x) if x.isdigit() else 10**18,x)):
        p=api_files.get(pid)
        if not p: continue
        payload=json.loads(p.read_text(encoding='utf-8')); ms=payload.get('matches') if isinstance(payload,dict) else None
        if not isinstance(ms,list): failures.append({'code':'SOURCE_PLAYER_MATCHES_INVALID','playerId':pid}); continue
        by_id=defaultdict(list); noid=[]
        for m in ms:
            mid=str(m.get('id') or '')
            if not mid: noid.append(m)
            else: by_id[mid].append(m)
        if noid: failures.append({'code':'MATCH_ID_MISSING','playerId':pid,'count':len(noid)})
        dedup=[]
        for mid,rows in by_id.items():
            if len(rows)==1: dedup.append(rows[0]); continue
            sigs={canon(r) for r in rows}
            if len(sigs)==1:
                dedup.append(rows[0]); duplicate_audit.append({'playerId':pid,'matchId':mid,'duplicateRows':len(rows),'status':'BYTE_SEMANTIC_IDENTICAL_PROVIDER_DUPLICATE_DEDUPED'})
            else:
                failures.append({'code':'NON_IDENTICAL_DUPLICATE_PROVIDER_MATCH_ID','playerId':pid,'matchId':mid,'rows':len(rows)})
        player_rows[pid]=dedup
        for m in dedup:
            try: sea=season(m.get('season'))
            except Exception: continue
            sr=refs_by_ps.get((pid,sea),[])
            if not sr: continue
            club_to_leagues=defaultdict(set)
            for r in sr:
                for c in r['_clubs']: club_to_leagues[c].add(r['_league'])
            h=str(m.get('h_team') or ''); a=str(m.get('a_team') or '')
            candidates=[]
            for c in (h,a):
                for lg in sorted(club_to_leagues.get(c,())): candidates.append((c,lg))
            candidates=sorted(set(candidates))
            if len(candidates)==2:
                ambiguous_requests[(str(m.get('id')),pid)]={'matchId':str(m.get('id')),'playerId':pid,'season':sea,'hTeam':h,'aTeam':a,'candidates':candidates}
            elif len(candidates)>2:
                failures.append({'code':'AMBIGUOUS_CANDIDATE_COUNT_GT2','playerId':pid,'matchId':str(m.get('id')),'count':len(candidates)})

    roster_cache={}; roster_meta=[]
    for i,mid in enumerate(sorted({k[0] for k in ambiguous_requests},key=lambda x:(int(x) if x.isdigit() else 10**18,x))):
        if i: time.sleep(args.delay)
        try:
            wire,raw,enc=fetch(MATCH_API.format(match_id=mid),ajax=True); payload=json.loads(raw.decode('utf-8'))
            roster_cache[mid]=payload; (roster_raw/f'match-{mid}-wire.bin').write_bytes(wire); (roster_raw/f'match-{mid}-api.json').write_bytes(raw)
            roster_meta.append({'matchId':mid,'wireBytes':len(wire),'wireSha256':H(wire),'decodedBytes':len(raw),'decodedSha256':H(raw),'contentEncoding':enc})
        except Exception as exc: failures.append({'code':'MATCH_ROSTER_REQUEST_FAILED','matchId':mid,'error':repr(exc)})

    resolved={}; resolution_audit=[]
    for key,req in sorted(ambiguous_requests.items()):
        mid,pid=key; payload=roster_cache.get(mid)
        if payload is None: continue
        side,err=roster_side(payload,pid)
        if err:
            failures.append({'code':'MATCH_ROSTER_PLAYER_SIDE_UNRESOLVED',**req,'reason':err}); continue
        selected=req['hTeam'] if side=='h' else req['aTeam']
        valid=[x for x in req['candidates'] if x[0]==selected]
        if len(valid)!=1:
            failures.append({'code':'MATCH_ROSTER_SIDE_NOT_IN_SOURCE_CANDIDATES',**req,'side':side,'selectedClub':selected,'valid':valid}); continue
        resolved[key]=valid[0]
        resolution_audit.append({**req,'rosterSide':side,'resolvedClub':valid[0][0],'league':valid[0][1],'status':'EXACT_PROVIDER_ROSTER_PLAYER_ID'})

    reconciliation=[]; segments=[]; unresolved_assign=[]
    for pid,ms in player_rows.items():
        assigned=[]
        for m in ms:
            mid=str(m.get('id') or '')
            try: sea=season(m.get('season'))
            except Exception: continue
            sr=refs_by_ps.get((pid,sea),[])
            if not sr: continue
            date=str(m.get('date') or '').split()[0]
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date): failures.append({'code':'MATCH_DATE_INVALID','playerId':pid,'matchId':mid,'date':m.get('date')}); continue
            club_to_leagues=defaultdict(set)
            for r in sr:
                for c in r['_clubs']: club_to_leagues[c].add(r['_league'])
            h=str(m.get('h_team') or ''); a=str(m.get('a_team') or '')
            cand=sorted(set((c,lg) for c in (h,a) for lg in club_to_leagues.get(c,())))
            if len(cand)==1: club,lg=cand[0]
            elif len(cand)==2 and (mid,pid) in resolved: club,lg=resolved[(mid,pid)]
            else:
                unresolved_assign.append({'playerId':pid,'matchId':mid,'season':sea,'hTeam':h,'aTeam':a,'candidates':cand}); continue
            obs={f:iv(m.get(f,0),f,pid,sea) for f in FIELDS if f!='games'}; obs['games']=1
            assigned.append({'playerId':pid,'personKey':pid_person[pid],'season':sea,'league':lg,'club':club,'matchId':mid,'date':date,'observations':obs})
        by_psl=defaultdict(list)
        for x in assigned: by_psl[(x['season'],x['league'])].append(x)
        for (spid,sea,lg),srows in refs.items():
            if spid!=pid: continue
            if len(srows)!=1: failures.append({'code':'SOURCE_DUPLICATE_PLAYER_SEASON_LEAGUE','playerId':pid,'season':sea,'league':lg}); continue
            sr=srows[0]; rows=by_psl.get((sea,lg),[]); sums={f:0 for f in FIELDS}; sums['games']=len(rows)
            for x in rows:
                for f in FIELDS:
                    if f!='games': sums[f]+=x['observations'][f]
            fr={}; exact=True
            for f in FIELDS:
                sv=iv(sr.get(f),f,pid,sea); mv=sums[f]; eq=sv==mv; fr[f]={'sourceAggregate':sv,'matchReconstruction':mv,'equal':eq}; exact &= eq
            reconciliation.append({'playerId':pid,'personKey':pid_person[pid],'season':sea,'league':lg,'sourceTeamTitle':sr.get('team_title'),'sourceClubs':sr['_clubs'],'assignedMatchRows':len(rows),'fieldResults':fr,'allObservedFieldsExact':bool(exact)})
        for sea in sorted({x['season'] for x in assigned}):
            seq=sorted([x for x in assigned if x['season']==sea],key=lambda x:(x['date'],int(x['matchId']) if x['matchId'].isdigit() else x['matchId']))
            current=None; ordn=0
            for x in seq:
                identity=(x['league'],x['club'])
                if current is None or (current['league'],current['club'])!=identity:
                    if current is not None: segments.append(current)
                    ordn+=1; current={'playerId':pid,'personKey':pid_person[pid],'season':sea,'league':x['league'],'club':x['club'],'segmentOrdinal':ordn,'firstObservedMatchDate':x['date'],'lastObservedMatchDate':x['date'],'matchCount':0,'observations':{f:0 for f in FIELDS},'temporalStatus':'VERIFIED_EVENT_RECONSTRUCTION','intervalSemantics':'OBSERVED_MATCH_SEQUENCE_NOT_CONTRACT_INTERVAL'}
                current['lastObservedMatchDate']=x['date']; current['matchCount']+=1
                for f in FIELDS: current['observations'][f]+=x['observations'][f]
            if current is not None: segments.append(current)

    bad=[r for r in reconciliation if not r['allObservedFieldsExact']]
    if unresolved_assign: failures.append({'code':'MATCH_ASSIGNMENT_RESIDUAL','count':len(unresolved_assign),'examples':unresolved_assign[:20]})
    if bad: failures.append({'code':'POST_REMEDIATION_RECONCILIATION_MISMATCH','count':len(bad),'examples':bad[:10]})
    if len(reconciliation)!=EXPECTED_REFS: failures.append({'code':'POST_REMEDIATION_REFERENCE_COUNT','expected':EXPECTED_REFS,'observed':len(reconciliation)})
    status='PASS' if not failures and len(reconciliation)==EXPECTED_REFS and not bad and not unresolved_assign else 'FAIL'
    metas={
        'reconciliation':write_jsonl(out/'reconciliation-v1-2.jsonl',reconciliation),
        'segments':write_jsonl(out/'segments-v1-2.jsonl',segments),
        'resolutionAudit':write_json(out/'roster-resolution-audit.json',resolution_audit),
        'duplicateAudit':write_json(out/'duplicate-match-dedup-audit.json',duplicate_audit),
        'rosterManifest':write_json(out/'roster-fetch-manifest.json',roster_meta),
    }
    report={'schema':'NEXUS_F2B_UNDERSTAT_RESIDUAL_REMEDIATION_V1','status':status,'capturedAt':datetime.now(timezone.utc).isoformat(),'source':{'runId':SOURCE_RUN_ID,'artifactDigestSha256':SOURCE_ARTIFACT_SHA256,'packageSha256':SOURCE_PACKAGE_SHA256,'pinnedAggregateSha256':US_SHA256},'counts':{'players':len(pid_person),'sourceReferences':len(reconciliation),'preRemediationAmbiguousPlayerMatchPairs':len(ambiguous_requests),'uniqueRosterMatchRequests':len({x[0] for x in ambiguous_requests}),'rosterResolutions':len(resolution_audit),'identicalDuplicatePlayerMatchRowsDeduped':sum(x['duplicateRows']-1 for x in duplicate_audit),'postRemediationMismatches':len(bad),'postRemediationUnresolvedAssignments':len(unresolved_assign),'segments':len(segments)},'files':metas,'failures':failures,'governance':{'fuzzyMatchingUsed':False,'currentGroupsUsedToOverridePinnedAggregate':False,'expectedMetricsReleased':False,'canonicalPredictiveEngineModified':False,'f2ParametersFitted':False},'temporalDecision':{'observedFieldsStatus':'VERIFIED_EVENT_RECONSTRUCTION' if status=='PASS' else 'BLOCKED','expectedFieldsStatus':'QUARANTINED_VINTAGE_REQUIRED'}}
    rep=write_json(out/'REMEDIATION_AUDIT.json',report)
    man=[]
    for p in sorted(x for x in out.rglob('*') if x.is_file() and x.name!='MANIFEST.json'):
        raw=p.read_bytes(); man.append({'path':str(p.relative_to(out)),'bytes':len(raw),'sha256':H(raw)})
    write_json(out/'MANIFEST.json',{'schema':'NEXUS_F2B_UNDERSTAT_RESIDUAL_REMEDIATION_MANIFEST_V1','status':status,'audit':rep,'files':man,'treeDigestSha256':H('\n'.join(f"{x['path']}\t{x['sha256']}\t{x['bytes']}" for x in man).encode())})
    print(json.dumps({'status':status,'players':len(pid_person),'references':len(reconciliation),'ambiguousPairs':len(ambiguous_requests),'resolutions':len(resolution_audit),'dedupedDuplicateRows':sum(x['duplicateRows']-1 for x in duplicate_audit),'mismatches':len(bad),'unresolvedAssignments':len(unresolved_assign),'failures':len(failures)},indent=2))
    if status!='PASS': raise SystemExit(2)
if __name__=='__main__': main()
