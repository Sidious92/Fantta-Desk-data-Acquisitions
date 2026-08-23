#!/usr/bin/env python3
import argparse
import csv
import gzip
import hashlib
import io
import json
import re
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

D1_COMMIT='d0cab101cc90f65ee0b1982e7ca974cd95c5d3b9'
D1_SHA256='952bdf1d4cfb81a0683bff1f78d949b6350b11be1cc27d20059f7ace651bb53c'
D1_URL=f'https://raw.githubusercontent.com/Sidious92/Fantta-Desk-data-Acquisitions/{D1_COMMIT}/data/nexus-d1/final-v3/IDENTITY_MASTER.json'
US_COMMIT='768b7ca0b977a5e6b4b429c7b0cf750e8269f2fc'
US_SHA256='b78fad5f01844a0fdab0d89474dafba9b86c586d2f0ce88f0ce2c9af70d2bc64'
US_URL=f'https://raw.githubusercontent.com/vibedatascience/understat_players_aggregated/{US_COMMIT}/understat_players_aggregated_2014_2024.csv'
API='https://understat.com/getPlayerData/{player_id}'
UA='Mozilla/5.0 (compatible; FantaNexus-F2-Full-Reconstruction/1.0)'
LEAGUES={'Serie_A','EPL','La_Liga','Bundesliga','Ligue_1','RFPL'}
FIELDS=['games','time','goals','npg','assists','shots','key_passes']
EXPECTED=['xG','npxG','xA','xGChain','xGBuildup']

def H(b): return hashlib.sha256(b).hexdigest()

def fetch(url, ajax=False):
    headers={'User-Agent':UA,'Accept':'application/json,text/plain,*/*','Accept-Encoding':'gzip'}
    if ajax: headers['X-Requested-With']='XMLHttpRequest'
    req=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(req,timeout=90) as r:
        wire=r.read(); enc=str(r.headers.get('Content-Encoding') or '').lower()
        if r.status!=200: raise RuntimeError(f'HTTP_{r.status}:{url}')
        raw=gzip.decompress(wire) if wire.startswith(b'\x1f\x8b') or 'gzip' in enc else wire
        return wire,raw,enc

def season(v):
    s=str(v or '').strip()
    m=re.fullmatch(r'(\d{4})/(\d{2})',s)
    if m:
        y=int(m.group(1)); yy=int(m.group(2))
        if yy != (y+1)%100: raise ValueError(s)
        return s
    if re.fullmatch(r'\d{4}',s):
        y=int(s); return f'{y}/{(y+1)%100:02d}'
    raise ValueError(s)

def iv(v,field,pid,sea):
    f=float(v); i=int(f)
    if f!=i: raise RuntimeError(f'NON_INTEGER:{pid}:{sea}:{field}:{v!r}')
    return i

def write_json(path,obj):
    raw=(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode(); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw); return {'path':str(path),'bytes':len(raw),'sha256':H(raw)}

def write_jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='\n') as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    raw=path.read_bytes(); return {'path':str(path),'bytes':len(raw),'rows':len(rows),'sha256':H(raw)}

def source_clubs(text): return [x.strip() for x in str(text or '').split(',') if x.strip()]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--shard-index',type=int,required=True); ap.add_argument('--shard-count',type=int,required=True); ap.add_argument('--delay',type=float,default=0.5); args=ap.parse_args()
    if args.shard_count<1 or not 0<=args.shard_index<args.shard_count: raise SystemExit('invalid shard args')
    out=Path(f'.nexus-f2-understat-full-reconstruction-v1/shard-{args.shard_index:02d}'); rawdir=out/'raw'; rawdir.mkdir(parents=True,exist_ok=True)
    d1_wire,d1_raw,_=fetch(D1_URL)
    if H(d1_raw)!=D1_SHA256: raise SystemExit('D1_HASH_MISMATCH')
    d1=json.loads(d1_raw); alias_to_person={}; duplicate_alias=[]
    for p in d1.get('persons',[]):
        if not p.get('globalPersonPromotionGranted'): continue
        for a in p.get('providerAliases',[]):
            if a.get('provider')=='Understat' and a.get('providerId') is not None:
                pid=str(a['providerId'])
                if pid in alias_to_person and alias_to_person[pid]!=p['personKey']: duplicate_alias.append(pid)
                alias_to_person[pid]=p['personKey']
    if duplicate_alias: raise SystemExit(f'DUPLICATE_D1_UNDERSTAT_ALIAS:{duplicate_alias[:10]}')
    all_ids=sorted(alias_to_person,key=lambda x:(int(x) if x.isdigit() else 10**18,x))
    shard_ids=[pid for i,pid in enumerate(all_ids) if i%args.shard_count==args.shard_index]

    us_wire,us_raw,_=fetch(US_URL)
    if H(us_raw)!=US_SHA256: raise SystemExit('PINNED_AGGREGATE_HASH_MISMATCH')
    source_rows=defaultdict(list); source_by_player_season=defaultdict(list)
    for r in csv.DictReader(io.StringIO(us_raw.decode('utf-8-sig'))):
        pid=str(r.get('id') or ''); league=str(r.get('league') or '')
        if pid not in alias_to_person or league not in LEAGUES: continue
        sea=season(r.get('season')); row={**r,'_season':sea,'_league':league,'_clubs':source_clubs(r.get('team_title'))}
        source_rows[(pid,sea,league)].append(row); source_by_player_season[(pid,sea)].append(row)

    failures=[]; player_index=[]; reconciliation=[]; segments=[]; assigned_matches=0; preserved_matches=0; request_failures=0
    for pos,pid in enumerate(shard_ids):
        if pos: time.sleep(args.delay)
        try:
            wire,decoded,encoding=fetch(API.format(player_id=pid),ajax=True); payload=json.loads(decoded.decode('utf-8')); matches=payload.get('matches') if isinstance(payload,dict) else None
            if not isinstance(matches,list): raise RuntimeError('INVALID_API_SHAPE')
        except Exception as exc:
            request_failures+=1; failures.append({'code':'PLAYER_REQUEST_OR_PARSE_FAILED','playerId':pid,'error':repr(exc)}); continue
        wire_path=rawdir/f'player-{pid}-wire.bin'; json_path=rawdir/f'player-{pid}-api.json'; wire_path.write_bytes(wire); json_path.write_bytes(decoded)
        preserved_matches+=len(matches); seen_match_ids=set(); assigned=[]
        for m in matches:
            mid=str(m.get('id') or ''); sea_raw=m.get('season')
            try: sea=season(sea_raw)
            except Exception:
                failures.append({'code':'MATCH_SEASON_INVALID','playerId':pid,'matchId':mid,'season':sea_raw}); continue
            date=str(m.get('date') or '').split()[0]
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date): failures.append({'code':'MATCH_DATE_INVALID','playerId':pid,'matchId':mid,'date':m.get('date')}); continue
            try: datetime.strptime(date,'%Y-%m-%d')
            except Exception: failures.append({'code':'MATCH_DATE_INVALID','playerId':pid,'matchId':mid,'date':m.get('date')}); continue
            if not mid or mid in seen_match_ids: failures.append({'code':'MATCH_ID_DUPLICATE_OR_MISSING','playerId':pid,'matchId':mid}); continue
            seen_match_ids.add(mid)
            refs=source_by_player_season.get((pid,sea),[])
            if not refs:
                continue
            club_to_leagues=defaultdict(set)
            for sr in refs:
                for club in sr['_clubs']: club_to_leagues[club].add(sr['_league'])
            hteam=str(m.get('h_team') or ''); ateam=str(m.get('a_team') or '')
            candidates=[]
            for club in (hteam,ateam):
                if club in club_to_leagues:
                    for league in sorted(club_to_leagues[club]): candidates.append((club,league))
            candidates=sorted(set(candidates))
            if len(candidates)!=1:
                failures.append({'code':'MATCH_CLUB_ASSIGNMENT_NOT_UNIQUE','playerId':pid,'season':sea,'matchId':mid,'hTeam':hteam,'aTeam':ateam,'candidates':candidates,'sourceClubs':sorted(club_to_leagues)}); continue
            club,league=candidates[0]
            obs={f:iv(m.get(f,0),f,pid,sea) for f in FIELDS if f!='games'}; obs['games']=1
            assigned.append({'playerId':pid,'personKey':alias_to_person[pid],'season':sea,'league':league,'club':club,'matchId':mid,'date':date,'observations':obs})
            assigned_matches+=1

        # Reconcile at exact provider player-season-league grain.
        by_psl=defaultdict(list)
        for x in assigned: by_psl[(x['season'],x['league'])].append(x)
        for (spid,sea,league),srows in sorted(source_rows.items()):
            if spid!=pid: continue
            if len(srows)!=1:
                failures.append({'code':'SOURCE_DUPLICATE_PLAYER_SEASON_LEAGUE','playerId':pid,'season':sea,'league':league,'rows':len(srows)}); continue
            sr=srows[0]; rr=by_psl.get((sea,league),[]); sums={f:0 for f in FIELDS}; sums['games']=len(rr)
            for x in rr:
                for f in FIELDS:
                    if f!='games': sums[f]+=x['observations'][f]
            field_results={}; exact=True
            for f in FIELDS:
                sv=iv(sr.get(f),f,pid,sea); mv=sums[f]; eq=sv==mv; field_results[f]={'sourceAggregate':sv,'matchReconstruction':mv,'equal':eq}; exact &= eq
            rec={'playerId':pid,'personKey':alias_to_person[pid],'season':sea,'league':league,'sourceTeamTitle':sr.get('team_title'),'sourceClubs':sr['_clubs'],'assignedMatchRows':len(rr),'fieldResults':field_results,'allObservedFieldsExact':bool(exact)}; reconciliation.append(rec)
            if not exact: failures.append({'code':'OBSERVED_FIELD_RECONCILIATION_MISMATCH','playerId':pid,'season':sea,'league':league,'fieldResults':field_results})

        # Build observed club segments from chronological assigned matches; this is an observed sequence, not a contract interval.
        for sea in sorted({x['season'] for x in assigned}):
            seq=sorted([x for x in assigned if x['season']==sea],key=lambda x:(x['date'],int(x['matchId']) if x['matchId'].isdigit() else x['matchId']))
            current=None
            for x in seq:
                identity=(x['league'],x['club'])
                if current is None or (current['league'],current['club'])!=identity:
                    if current is not None: segments.append(current)
                    ordinal=1+sum(1 for s in segments if s['playerId']==pid and s['season']==sea)
                    current={'playerId':pid,'personKey':alias_to_person[pid],'season':sea,'league':x['league'],'club':x['club'],'segmentOrdinal':ordinal,'firstObservedMatchDate':x['date'],'lastObservedMatchDate':x['date'],'matchCount':0,'observations':{f:0 for f in FIELDS},'temporalStatus':'VERIFIED_EVENT_RECONSTRUCTION','intervalSemantics':'OBSERVED_MATCH_SEQUENCE_NOT_CONTRACT_INTERVAL'}
                current['lastObservedMatchDate']=x['date']; current['matchCount']+=1
                for f in FIELDS: current['observations'][f]+=x['observations'][f]
            if current is not None: segments.append(current)
        player_index.append({'playerId':pid,'personKey':alias_to_person[pid],'wireBytes':len(wire),'wireSha256':H(wire),'decodedBytes':len(decoded),'decodedSha256':H(decoded),'contentEncoding':encoding,'providerMatchRows':len(matches),'assignedReferenceMatchRows':len(assigned),'sourceReferenceRows':sum(len(v) for (p,_,_),v in source_rows.items() if p==pid)})

    recon_exact=sum(1 for r in reconciliation if r['allObservedFieldsExact'])
    status='PASS' if not failures and request_failures==0 and recon_exact==len(reconciliation) and len(player_index)==len(shard_ids) else 'FAIL'
    seg_meta=write_jsonl(out/'segments.jsonl',segments); rec_meta=write_jsonl(out/'reconciliation.jsonl',reconciliation); idx_meta=write_json(out/'player-index.json',player_index)
    registry={'schema':'NEXUS_F2_UNDERSTAT_FULL_RECONSTRUCTION_SHARD_V1','status':status,'capturedAt':datetime.now(timezone.utc).isoformat(),'shardIndex':args.shard_index,'shardCount':args.shard_count,'d1':{'commit':D1_COMMIT,'sha256':D1_SHA256,'exactUnderstatAliases':len(all_ids),'assignedToShard':len(shard_ids)},'source':{'provider':'UNDERSTAT','endpoint':'getPlayerData/{player_id}','aggregateCommit':US_COMMIT,'aggregateSha256':US_SHA256},'counts':{'playersExpected':len(shard_ids),'playersFetched':len(player_index),'requestFailures':request_failures,'providerMatchRowsPreserved':preserved_matches,'referenceMatchRowsAssigned':assigned_matches,'sourceReferenceComparisons':len(reconciliation),'exactSourceReferenceComparisons':recon_exact,'observedClubSegments':len(segments),'failures':len(failures)},'files':{'segments':seg_meta,'reconciliation':rec_meta,'playerIndex':idx_meta},'failures':failures,'governance':{'expectedFieldsPreservedInRawOnly':EXPECTED,'expectedFieldsReleased':False,'fuzzyMatchingUsed':False,'f2ParametersFitted':False,'canonicalPredictiveEngineModified':False}}
    write_json(out/'SHARD_REGISTRY.json',registry)
    print(json.dumps({'status':status,'shard':args.shard_index,'players':len(player_index),'expectedPlayers':len(shard_ids),'comparisons':len(reconciliation),'exact':recon_exact,'segments':len(segments),'failures':len(failures)},indent=2))
    if status!='PASS': raise SystemExit(2)

if __name__=='__main__': main()
