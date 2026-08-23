#!/usr/bin/env python3
import argparse,hashlib,json
from pathlib import Path
from datetime import datetime,timezone
from collections import defaultdict

MATCHES={'23028':['2437','10561'],'29482':['11383','12322']}
PLAYER_EVENT_ID_FIELDS=['id','season','date','h_team','a_team']
PLAYER_RELEASED_OBS=['time','goals','npg','assists','shots','key_passes']
PLAYER_ALLOWED_DIFFS={'roster_id','xG','npxG','xA','xGChain','xGBuildup'}
ROSTER_INVARIANT_FIELDS=['player_id','team_id','h_a','position','time','goals','shots','key_passes','assists','yellow_card','red_card','own_goals']
ROSTER_ALLOWED_DIFFS={'id','roster_in','roster_out','xG','xA','xGChain','xGBuildup'}
FULL_PACKAGE_SHA='00a60a8a8b645e9bf171a354a4adb547c85b70085974596b093ea3dd7d5b329c'
PROBE_V1_PACKAGE_SHA='ed97c53c681f0f57c3450ca39be832550352017cbdef5fe9d55c0d34e505e959'

def H(b): return hashlib.sha256(b).hexdigest()
def canon(v): return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def write(path,obj):
    raw=(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode(); path.write_bytes(raw); return {'bytes':len(raw),'sha256':H(raw)}
def diffs(rows):
    keys=sorted(set().union(*(r.keys() for r in rows)))
    return [k for k in keys if len({canon(r.get(k)) for r in rows})>1]
def find_player_file(root,pid):
    xs=list(root.rglob(f'player-{pid}-api.json'))
    if len(xs)!=1: raise RuntimeError(f'PLAYER_FILE_COUNT:{pid}:{len(xs)}')
    return xs[0]
def roster_rows(payload,pid):
    out=[]
    for side in ('h','a'):
        side_obj=(payload.get('rosters',{}).get(side,{}) or {}) if isinstance(payload,dict) else {}
        for rid,row in side_obj.items():
            if isinstance(row,dict) and str(row.get('player_id') or '')==str(pid): out.append({'side':side,'rosterKey':str(rid),'row':row})
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--full-root',required=True); ap.add_argument('--probe-v1-raw-root',required=True); ap.add_argument('--output-root',required=True); args=ap.parse_args()
    full=Path(args.full_root); rawroot=Path(args.probe_v1_raw_root); out=Path(args.output_root); out.mkdir(parents=True,exist_ok=True)
    failures=[]; evidence=[]
    for mid,pids in MATCHES.items():
        match_path=rawroot/f'match-{mid}-api.json'
        if not match_path.exists(): failures.append({'code':'FROZEN_MATCH_RAW_MISSING','matchId':mid}); continue
        match_payload=json.loads(match_path.read_text(encoding='utf-8'))
        for pid in pids:
            pdata=json.loads(find_player_file(full,pid).read_text(encoding='utf-8'))
            prows=[m for m in pdata.get('matches',[]) if str(m.get('id') or '')==mid]
            if len(prows)!=2:
                failures.append({'code':'PLAYER_DUPLICATE_PAIR_COUNT','playerId':pid,'matchId':mid,'rows':len(prows)}); continue
            p_diff=diffs(prows)
            p_identity_equal=all(len({canon(r.get(k)) for r in prows})==1 for k in PLAYER_EVENT_ID_FIELDS)
            p_observed_equal=all(len({canon(r.get(k)) for r in prows})==1 for k in PLAYER_RELEASED_OBS)
            p_allowed=set(p_diff).issubset(PLAYER_ALLOWED_DIFFS)

            rwrap=roster_rows(match_payload,pid); rrows=[x['row'] for x in rwrap]
            if len(rrows)!=2:
                failures.append({'code':'MATCH_ROSTER_DUPLICATE_PAIR_COUNT','playerId':pid,'matchId':mid,'rows':len(rrows)}); continue
            r_diff=diffs(rrows)
            r_invariants_equal=all(len({canon(r.get(k)) for r in rrows})==1 for k in ROSTER_INVARIANT_FIELDS)
            r_allowed=set(r_diff).issubset(ROSTER_ALLOWED_DIFFS)
            sides=sorted({x['side'] for x in rwrap}); teams=sorted({str(x['row'].get('team_id') or '') for x in rwrap}); positions=sorted({str(x['row'].get('position') or '') for x in rwrap})
            same_side_team_position=(len(sides)==1 and len(teams)==1 and len(positions)==1)

            roster_matches_player=True; roster_player_comparison=[]
            # Both technical roster rows must agree with the duplicated player rows on every released roster-observable field.
            canonical_player_obs={k:str(prows[0].get(k)) for k in ['time','goals','shots','key_passes','assists']}
            for i,r in enumerate(rrows):
                checks={k:(str(r.get(k))==canonical_player_obs[k]) for k in canonical_player_obs}
                roster_matches_player &= all(checks.values())
                roster_player_comparison.append({'rosterIndex':i,'checks':checks})

            valid=(p_identity_equal and p_observed_equal and p_allowed and r_invariants_equal and r_allowed and same_side_team_position and roster_matches_player)
            rec={'matchId':mid,'playerId':pid,'playerApiRows':2,'playerApiDifferingFields':p_diff,'playerEventIdentityEqual':p_identity_equal,'playerReleasedObservedEqual':p_observed_equal,'playerApiDifferencesAllowed':p_allowed,'matchRosterRows':2,'matchRosterDifferingFields':r_diff,'matchRosterInvariantFieldsEqual':r_invariants_equal,'matchRosterDifferencesAllowed':r_allowed,'matchRosterSides':sides,'matchRosterTeamIds':teams,'matchRosterPositions':positions,'sameSideTeamPosition':same_side_team_position,'matchRosterObservedMatchesPlayerApi':roster_matches_player,'rosterPlayerComparison':roster_player_comparison,'rawTechnicalRowsPreserved':True,'validDuplicateTechnicalRowsForSingleObservedEvent':valid}
            evidence.append(rec)
            if not valid: failures.append({'code':'DUPLICATE_TECHNICAL_ROW_VALIDATION_FAILED',**rec})
    status='PASS' if not failures and len(evidence)==4 else 'FAIL'
    report={'schema':'NEXUS_F2B_UNDERSTAT_DUPLICATE_EVENT_PROBE_V2','status':status,'capturedAt':datetime.now(timezone.utc).isoformat(),'frozenInputs':{'fullReconstructionPackageSha256':FULL_PACKAGE_SHA,'duplicateProbeV1PackageSha256':PROBE_V1_PACKAGE_SHA},'criteria':{'oneProviderMatchIdDefinesOneFootballEvent':True,'playerApiEventIdentityFields':PLAYER_EVENT_ID_FIELDS,'playerApiReleasedObservedFields':PLAYER_RELEASED_OBS,'playerApiAllowedDifferingFields':sorted(PLAYER_ALLOWED_DIFFS),'matchRosterInvariantFields':ROSTER_INVARIANT_FIELDS,'matchRosterAllowedDifferingFields':sorted(ROSTER_ALLOWED_DIFFS),'requiredSameSideTeamPosition':True,'rawRowsMustRemainPreserved':True},'counts':{'validatedPlayerMatchPairs':len(evidence),'validPairs':sum(1 for x in evidence if x['validDuplicateTechnicalRowsForSingleObservedEvent']),'failures':len(failures)},'evidence':evidence,'failures':failures,'decision':{'onPass':'The four provider duplicate player-match pairs are validated as duplicate technical rows for one observed football event. The observed F2 family may count each playerId+matchId once while retaining every raw row. Any aggregate/reference row that counts those technical duplicates more than once must be typed as duplicate-event-contaminated QA evidence rather than forcing the event reconstruction to double-count.','expectedMetricsStatus':'QUARANTINED_VINTAGE_REQUIRED','aggregateOverrideGranted':False,'f2ObservedReleaseGrantedByThisProbeAlone':False},'governance':{'f2ParametersFitted':False,'canonicalPredictiveEngineModified':False,'expectedMetricsPromoted':False,'fuzzyMatchingUsed':False}}
    meta=write(out/'DUPLICATE_EVENT_PROBE_V2.json',report)
    write(out/'MANIFEST.json',{'schema':'NEXUS_F2B_UNDERSTAT_DUPLICATE_EVENT_PROBE_V2_MANIFEST','status':status,'probe':meta})
    print(json.dumps({'status':status,'pairs':len(evidence),'valid':sum(1 for x in evidence if x['validDuplicateTechnicalRowsForSingleObservedEvent']),'failures':len(failures)},indent=2))
    if status!='PASS': raise SystemExit(2)
if __name__=='__main__': main()
