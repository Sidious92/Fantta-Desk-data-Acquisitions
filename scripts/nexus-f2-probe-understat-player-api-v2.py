#!/usr/bin/env python3
import csv
import hashlib
import io
import json
import re
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

OUT = Path('.nexus-f2-understat-player-match-temporal-probe-v2')
RAW = OUT / 'raw'
UNDERSTAT_COMMIT = '768b7ca0b977a5e6b4b429c7b0cf750e8269f2fc'
UNDERSTAT_SHA256 = 'b78fad5f01844a0fdab0d89474dafba9b86c586d2f0ce88f0ce2c9af70d2bc64'
CSV_URL = f'https://raw.githubusercontent.com/vibedatascience/understat_players_aggregated/{UNDERSTAT_COMMIT}/understat_players_aggregated_2014_2024.csv'
API_URL = 'https://understat.com/getPlayerData/{player_id}'
UA = 'Mozilla/5.0 (compatible; FantaNexus-F2-Temporal-Probe/2.0)'
OBSERVED = ['games','time','goals','npg','assists','shots','key_passes']
EXPECTED = ['xG','npxG','xA','xGChain','xGBuildup']
COHORT = [
 {'playerId':'1305','name':'Lukasz Skorupski','classicRole':'P'},
 {'playerId':'1093','name':'Mattia Perin','classicRole':'P'},
 {'playerId':'1541','name':'Stefan de Vrij','classicRole':'D'},
 {'playerId':'1463','name':'Francesco Acerbi','classicRole':'D'},
 {'playerId':'1471','name':'Lorenzo Pellegrini','classicRole':'C'},
 {'playerId':'1122','name':'Manuel Locatelli','classicRole':'C'},
 {'playerId':'1294','name':'Paulo Dybala','classicRole':'A'},
 {'playerId':'1612','name':'Domenico Berardi','classicRole':'A'}
]

def h(b): return hashlib.sha256(b).hexdigest()

def fetch(url, ajax=False):
    headers={'User-Agent':UA,'Accept':'application/json,text/plain,*/*'}
    if ajax: headers['X-Requested-With']='XMLHttpRequest'
    req=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(req,timeout=90) as r:
        if r.status != 200: raise RuntimeError(f'HTTP_{r.status}:{url}')
        return r.read()

def season(v):
    s=str(v or '').strip()
    if re.fullmatch(r'\d{4}/\d{2}',s): return s
    if re.fullmatch(r'\d{4}',s):
        y=int(s); return f'{y}/{(y+1)%100:02d}'
    raise RuntimeError(f'INVALID_SEASON:{s!r}')

def iv(v, field, pid, sea):
    try:
        f=float(v); i=int(f)
        if f != i: raise ValueError
        return i
    except Exception as e: raise RuntimeError(f'NON_INTEGER:{pid}:{sea}:{field}:{v!r}') from e

def write_json(path,obj):
    raw=(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode()
    path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw)
    return {'path':str(path.relative_to(OUT)),'bytes':len(raw),'sha256':h(raw)}

def reconstruct(rows,pid,sea):
    out={k:0 for k in OBSERVED}; out['games']=len(rows); dates=[]; ids=set()
    for r in rows:
        d=str(r.get('date') or '').split()[0]
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',d): raise RuntimeError(f'INVALID_DATE:{pid}:{sea}:{r.get("id")}')
        datetime.strptime(d,'%Y-%m-%d'); dates.append(d)
        mid=str(r.get('id') or '')
        if not mid or mid in ids: raise RuntimeError(f'INVALID_MATCH_ID:{pid}:{sea}:{mid!r}')
        ids.add(mid)
        for f in ['time','goals','npg','assists','shots','key_passes']: out[f]+=iv(r.get(f,0),f,pid,sea)
    out['firstMatchDate']=min(dates); out['lastMatchDate']=max(dates)
    return out

def main():
    OUT.mkdir(parents=True,exist_ok=True); RAW.mkdir(parents=True,exist_ok=True)
    csv_raw=fetch(CSV_URL)
    if h(csv_raw) != UNDERSTAT_SHA256: raise RuntimeError('PINNED_CSV_SHA256_MISMATCH')
    ids={x['playerId'] for x in COHORT}; src=defaultdict(list)
    for r in csv.DictReader(io.StringIO(csv_raw.decode('utf-8-sig'))):
        pid=str(r.get('id') or '')
        if pid in ids and r.get('league')=='Serie_A': src[(pid,season(r.get('season')))].append(r)
    failures=[]; comps=[]; evidence=[]; total=dated=0
    for ix,subject in enumerate(COHORT):
        if ix: time.sleep(1)
        pid=subject['playerId']; raw=fetch(API_URL.format(player_id=pid),ajax=True)
        (RAW/f'player-{pid}-api.json').write_bytes(raw)
        payload=json.loads(raw)
        matches=payload.get('matches') if isinstance(payload,dict) else None
        if not isinstance(matches,list): raise RuntimeError(f'INVALID_API_SHAPE:{pid}:{type(payload).__name__}')
        total+=len(matches); dated+=sum(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}',str(x.get('date') or '').split()[0])) for x in matches)
        by=defaultdict(list)
        for x in matches: by[season(x.get('season'))].append(x)
        rows_for=sorted((s,rows) for (p,s),rows in src.items() if p==pid)
        evidence.append({**subject,'apiBytes':len(raw),'apiSha256':h(raw),'matchRows':len(matches),'pinnedSerieASeasonRows':len(rows_for),'payloadKeys':sorted(payload.keys())})
        for sea,rows in rows_for:
            if len(rows)!=1:
                failures.append({'code':'SOURCE_DUPLICATE','playerId':pid,'season':sea,'rows':len(rows)}); continue
            mr=by.get(sea,[])
            if not mr:
                failures.append({'code':'MATCH_ROWS_MISSING','playerId':pid,'season':sea}); continue
            agg=reconstruct(mr,pid,sea); sr=rows[0]; fr={}; exact=True
            for f in OBSERVED:
                a=iv(sr.get(f),f,pid,sea); b=agg[f]; eq=a==b; fr[f]={'sourceAggregate':a,'matchReconstruction':b,'equal':eq}; exact &= eq
            rec={'playerId':pid,'playerName':subject['name'],'classicRole':subject['classicRole'],'season':sea,'sourceTeamTitle':sr.get('team_title'),'sourceMultiClub':',' in str(sr.get('team_title') or ''),'firstMatchDate':agg['firstMatchDate'],'lastMatchDate':agg['lastMatchDate'],'matchCount':agg['games'],'fieldResults':fr,'allObservedFieldsExact':bool(exact)}
            comps.append(rec)
            if not exact: failures.append({'code':'RECONCILIATION_MISMATCH','playerId':pid,'season':sea,'fieldResults':fr})
    exact=sum(x['allObservedFieldsExact'] for x in comps); status='PASS' if comps and not failures and exact==len(comps) and total==dated else 'FAIL'
    report={'schema':'NEXUS_F2_UNDERSTAT_PLAYER_MATCH_TEMPORAL_PROBE_V2','status':status,'capturedAt':datetime.now(timezone.utc).isoformat(),'source':{'provider':'UNDERSTAT','endpoint':'getPlayerData/{player_id}','endpointMethod':'GET_X_REQUESTED_WITH_XMLHTTPREQUEST','pinnedAggregateCommit':UNDERSTAT_COMMIT,'pinnedAggregateSha256':UNDERSTAT_SHA256},'supersedes':['NEXUS_F2_UNDERSTAT_PLAYER_MATCH_TEMPORAL_PROBE_V1','NEXUS_F2_UNDERSTAT_PLAYER_MATCH_TEMPORAL_PROBE_V1_1'],'cohort':{'players':len(COHORT),'selection':'DETERMINISTIC_EXACT_F1_D1_BOUND_LONG_HISTORY_TWO_PER_CLASSIC_ROLE'},'matchShape':{'totalRows':total,'datedRows':dated,'allRowsDated':total>0 and total==dated},'reconciliation':{'comparisons':len(comps),'exactComparisons':exact,'allComparedSeasonsExact':len(comps)>0 and exact==len(comps),'fields':OBSERVED,'rows':comps},'temporalDecision':{'observedEventStableFields':'ELIGIBLE_FOR_FULL_RECONSTRUCTION_PILOT_IF_PROBE_PASS','expectedModelFields':EXPECTED,'expectedModelFieldsReleased':False,'expectedMetricReason':'Match occurrence dates do not establish provider-model expected-metric historical vintage/invariance.'},'playerEvidence':evidence,'failures':failures,'governance':{'newProviderIntroduced':False,'fuzzyMatchingUsed':False,'f2ParametersFitted':False,'expectedMetricsPromoted':False,'canonicalPredictiveEngineModified':False}}
    pm=write_json(OUT/'PROBE.json',report)
    raw_meta=[{'path':str(p.relative_to(OUT)),'bytes':p.stat().st_size,'sha256':h(p.read_bytes())} for p in sorted(RAW.iterdir()) if p.is_file()]
    mm=write_json(OUT/'MANIFEST.json',{'schema':'NEXUS_F2_UNDERSTAT_PLAYER_MATCH_TEMPORAL_PROBE_MANIFEST_V2','status':status,'probe':pm,'rawFiles':raw_meta})
    print(json.dumps({'status':status,'players':len(COHORT),'matchRows':total,'comparisons':len(comps),'exactComparisons':exact,'failureCount':len(failures),'probeSha256':pm['sha256'],'manifestSha256':mm['sha256']},indent=2))
    if status!='PASS': raise SystemExit(2)

if __name__=='__main__': main()
