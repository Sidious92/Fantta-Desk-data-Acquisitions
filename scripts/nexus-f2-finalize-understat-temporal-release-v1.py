#!/usr/bin/env python3
import argparse,hashlib,json
from collections import Counter
from pathlib import Path
from datetime import datetime,timezone

FIELDS=['games','time','goals','npg','assists','shots','key_passes']
EXPECTED_REFS=8399
EXPECTED_EXACT=8397
EXPECTED_CONTAMINATED=2
EXPECTED_PLAYERS=2048
REMEDIATION_PACKAGE_SHA='dcb0b65999e4321b495c8217733cff40472b54a21d2ddd3b69e647a4e6321d30'
DUP_PROBE_PACKAGE_SHA='07ad16e604ae28baf0e2a9a0877c5e788300eefd7d7f5d1da6336dc872bbfe53'
FULL_RECON_PACKAGE_SHA='00a60a8a8b645e9bf171a354a4adb547c85b70085974596b093ea3dd7d5b329c'
EXCEPTIONS={
 ('2437','2023/24','La_Liga'):{'matchId':'23028','delta':{'games':1,'time':90,'goals':0,'npg':0,'assists':0,'shots':1,'key_passes':0}},
 ('10561','2023/24','La_Liga'):{'matchId':'23028','delta':{'games':1,'time':64,'goals':0,'npg':0,'assists':0,'shots':1,'key_passes':0}},
}

def H(b): return hashlib.sha256(b).hexdigest()
def load(path): return json.loads(path.read_text(encoding='utf-8'))
def load_jsonl(path):
    with path.open(encoding='utf-8') as f:
        for line in f:
            if line.strip(): yield json.loads(line)
def write(path,obj):
    raw=(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode(); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw); return {'path':str(path),'bytes':len(raw),'sha256':H(raw)}
def write_jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='\n') as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    raw=path.read_bytes(); return {'path':str(path),'bytes':len(raw),'rows':len(rows),'sha256':H(raw)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--remediation-root',required=True); ap.add_argument('--probe-root',required=True); ap.add_argument('--output-root',required=True); args=ap.parse_args()
    rem=Path(args.remediation_root); probe=Path(args.probe_root); out=Path(args.output_root); out.mkdir(parents=True,exist_ok=True)
    failures=[]
    rem_audit=load(rem/'REMEDIATION_AUDIT.json'); probe_audit=load(probe/'DUPLICATE_EVENT_PROBE_V2.json')
    if rem_audit.get('schema')!='NEXUS_F2B_UNDERSTAT_RESIDUAL_REMEDIATION_V1_1': failures.append({'code':'REMEDIATION_SCHEMA_INVALID'})
    if probe_audit.get('status')!='PASS' or probe_audit.get('counts',{}).get('validPairs')!=4: failures.append({'code':'DUPLICATE_EVENT_PROBE_NOT_PASS','status':probe_audit.get('status'),'validPairs':probe_audit.get('counts',{}).get('validPairs')})
    if rem_audit.get('counts',{}).get('players')!=EXPECTED_PLAYERS: failures.append({'code':'PLAYER_COUNT_MISMATCH','expected':EXPECTED_PLAYERS,'observed':rem_audit.get('counts',{}).get('players')})
    if rem_audit.get('counts',{}).get('postRemediationUnresolvedAssignments')!=0: failures.append({'code':'UNRESOLVED_CLUB_ASSIGNMENTS','count':rem_audit.get('counts',{}).get('postRemediationUnresolvedAssignments')})
    # The superseded remediation must have failed only because of the two reconciliation residuals.
    non_recon_fail=[x for x in rem_audit.get('failures',[]) if x.get('code')!='POST_REMEDIATION_RECONCILIATION_MISMATCH']
    if non_recon_fail: failures.append({'code':'UNEXPECTED_REMEDIATION_FAILURE_CLASS','failures':non_recon_fail})

    validated_pairs={(str(x['playerId']),str(x['matchId'])) for x in probe_audit.get('evidence',[]) if x.get('validDuplicateTechnicalRowsForSingleObservedEvent')}
    rec_path=rem/'reconciliation-v1-2.jsonl'; seg_path=rem/'segments-v1-2.jsonl'
    recs=list(load_jsonl(rec_path)); segs=list(load_jsonl(seg_path))
    if len(recs)!=EXPECTED_REFS: failures.append({'code':'REFERENCE_COUNT_MISMATCH','expected':EXPECTED_REFS,'observed':len(recs)})
    final_recs=[]; exact=0; contaminated=0; unexplained=[]
    seen=[]
    for r in recs:
        key=(str(r['playerId']),str(r['season']),str(r['league'])); seen.append(key)
        rr=dict(r)
        if r.get('allObservedFieldsExact'):
            exact+=1; rr['qaStatus']='EXACT_PINNED_REFERENCE'; rr['temporalReleaseStatus']='VERIFIED_EVENT_RECONSTRUCTION'
        else:
            ex=EXCEPTIONS.get(key)
            if ex is None:
                unexplained.append({'key':key,'reason':'NOT_LISTED_EXCEPTION'}); rr['qaStatus']='UNEXPLAINED_MISMATCH'; final_recs.append(rr); continue
            if (key[0],ex['matchId']) not in validated_pairs:
                unexplained.append({'key':key,'reason':'DUPLICATE_EVENT_NOT_VALIDATED'}); rr['qaStatus']='UNEXPLAINED_MISMATCH'; final_recs.append(rr); continue
            delta={}
            delta_ok=True
            for f in FIELDS:
                fr=r['fieldResults'][f]; d=fr['sourceAggregate']-fr['matchReconstruction']; delta[f]=d
                if d!=ex['delta'][f]: delta_ok=False
            if not delta_ok:
                unexplained.append({'key':key,'reason':'DELTA_NOT_EQUAL_VALIDATED_DUPLICATE_EVENT','delta':delta,'expected':ex['delta']}); rr['qaStatus']='UNEXPLAINED_MISMATCH'
            else:
                contaminated+=1; rr['qaStatus']='QUARANTINED_DUPLICATE_EVENT_CONTAMINATED_REFERENCE'; rr['temporalReleaseStatus']='VERIFIED_EVENT_RECONSTRUCTION'; rr['aggregateReferenceUse']='QA_QUARANTINED_NOT_PRIMARY'; rr['duplicateEventEvidence']={'matchId':ex['matchId'],'delta':delta,'probeStatus':'PASS'}
        final_recs.append(rr)
    dup_keys=[k for k,v in Counter(seen).items() if v!=1]
    if dup_keys: failures.append({'code':'REFERENCE_KEY_NOT_UNIQUE','count':len(dup_keys),'examples':dup_keys[:20]})
    if exact!=EXPECTED_EXACT: failures.append({'code':'EXACT_REFERENCE_COUNT','expected':EXPECTED_EXACT,'observed':exact})
    if contaminated!=EXPECTED_CONTAMINATED: failures.append({'code':'CONTAMINATED_REFERENCE_COUNT','expected':EXPECTED_CONTAMINATED,'observed':contaminated})
    if unexplained: failures.append({'code':'UNEXPLAINED_MISMATCH','count':len(unexplained),'examples':unexplained[:10]})
    used_exceptions={k for k in seen if k in EXCEPTIONS and any(r['qaStatus']=='QUARANTINED_DUPLICATE_EVENT_CONTAMINATED_REFERENCE' and (str(r['playerId']),str(r['season']),str(r['league']))==k for r in final_recs)}
    if used_exceptions!=set(EXCEPTIONS): failures.append({'code':'EXCEPTION_SET_NOT_EXACT','expected':[list(x) for x in sorted(EXCEPTIONS)],'used':[list(x) for x in sorted(used_exceptions)]})

    seg_keys=[(s['personKey'],s['season'],s['league'],s['segmentOrdinal']) for s in segs]
    dup_seg=[k for k,v in Counter(seg_keys).items() if v!=1]
    if dup_seg: failures.append({'code':'SEGMENT_KEY_NOT_UNIQUE','count':len(dup_seg),'examples':dup_seg[:20]})
    impossible=[]
    for s in segs:
        o=s.get('observations',{})
        if o.get('games')!=s.get('matchCount') or any(isinstance(v,(int,float)) and v<0 for v in o.values()) or o.get('npg',0)>o.get('goals',0): impossible.append({'playerId':s.get('playerId'),'season':s.get('season'),'league':s.get('league'),'segmentOrdinal':s.get('segmentOrdinal')})
    if impossible: failures.append({'code':'IMPOSSIBLE_SEGMENT_VALUES','count':len(impossible),'examples':impossible[:20]})

    status='PASS' if not failures else 'FAIL'
    rec_meta=write_jsonl(out/'released-observed-reconciliation-v1.jsonl',final_recs)
    seg_meta=write_jsonl(out/'released-observed-segments-v1.jsonl',segs)
    audit={'schema':'NEXUS_F2B_UNDERSTAT_TEMPORAL_RELEASE_FINAL_AUDIT_V1','status':status,'capturedAt':datetime.now(timezone.utc).isoformat(),'frozenInputs':{'fullReconstructionPackageSha256':FULL_RECON_PACKAGE_SHA,'residualRemediationV1_1PackageSha256':REMEDIATION_PACKAGE_SHA,'duplicateEventProbeV2PackageSha256':DUP_PROBE_PACKAGE_SHA},'counts':{'d1ExactUnderstatPlayers':rem_audit.get('counts',{}).get('players'),'sourceReferences':len(recs),'exactPinnedReferences':exact,'typedDuplicateEventContaminatedReferences':contaminated,'unexplainedMismatches':len(unexplained),'unresolvedClubAssignments':rem_audit.get('counts',{}).get('postRemediationUnresolvedAssignments'),'releasedObservedSegments':len(segs),'validatedDuplicatePlayerMatchPairs':len(validated_pairs)},'exceptionSet':[{'playerId':k[0],'season':k[1],'league':k[2],'matchId':v['matchId'],'requiredDelta':v['delta']} for k,v in sorted(EXCEPTIONS.items())],'validation':{'ordinaryReferencesExact':exact==EXPECTED_EXACT,'typedContaminatedReferencesExact':contaminated==EXPECTED_CONTAMINATED,'unexplainedMismatchCountZero':not unexplained,'clubAssignmentsResolved':rem_audit.get('counts',{}).get('postRemediationUnresolvedAssignments')==0,'referenceKeysUnique':not dup_keys,'segmentKeysUnique':not dup_seg,'impossibleSegmentValues':len(impossible),'rawDuplicateRowsPreservedUpstream':True,'fuzzyMatchingUsed':False,'expectedMetricsReleased':False,'aggregateUsedAsPrimaryEvidence':False,'canonicalPredictiveEngineModified':False,'f2ParametersFitted':False},'temporalDecision':{'releasedObservedFields':['games','time','goals','npg','assists','shots','key_passes'],'observedFieldsStatus':'VERIFIED_EVENT_RECONSTRUCTION' if status=='PASS' else 'BLOCKED','expectedFields':['xG','npxG','xA','xGChain','xGBuildup'],'expectedFieldsStatus':'QUARANTINED_VINTAGE_REQUIRED','aggregateReferenceRole':'QA_ONLY_WITH_TWO_TYPED_CONTAMINATED_REFERENCES'},'files':{'reconciliation':rec_meta,'segments':seg_meta},'failures':failures}
    audit_meta=write(out/'F2B_FINAL_AUDIT.json',audit)
    files=[]
    for p in sorted(x for x in out.rglob('*') if x.is_file() and x.name!='MANIFEST.json'):
        raw=p.read_bytes(); files.append({'path':str(p.relative_to(out)),'bytes':len(raw),'sha256':H(raw)})
    tree=H('\n'.join(f"{x['path']}\t{x['sha256']}\t{x['bytes']}" for x in files).encode())
    write(out/'MANIFEST.json',{'schema':'NEXUS_F2B_UNDERSTAT_TEMPORAL_RELEASE_MANIFEST_V1','status':status,'audit':audit_meta,'treeDigestSha256':tree,'files':files})
    print(json.dumps({'status':status,'references':len(recs),'exact':exact,'contaminated':contaminated,'unexplained':len(unexplained),'segments':len(segs),'failures':len(failures),'treeDigest':tree},indent=2))
    if status!='PASS': raise SystemExit(2)
if __name__=='__main__': main()
