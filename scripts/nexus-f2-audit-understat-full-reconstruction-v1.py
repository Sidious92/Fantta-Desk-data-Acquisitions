#!/usr/bin/env python3
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_SHARDS=8
EXPECTED_D1_ALIASES=2048

def H(b): return hashlib.sha256(b).hexdigest()
def load_json(path): return json.loads(path.read_text(encoding='utf-8'))
def load_jsonl(path):
    with path.open(encoding='utf-8') as f:
        for line in f:
            if line.strip(): yield json.loads(line)
def write_json(path,obj):
    raw=(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode(); path.write_bytes(raw); return {'path':str(path),'bytes':len(raw),'sha256':H(raw)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input-root',required=True); ap.add_argument('--output-root',required=True); ap.add_argument('--run-id',required=True); args=ap.parse_args()
    root=Path(args.input_root); out=Path(args.output_root); out.mkdir(parents=True,exist_ok=True)
    regs=sorted(root.rglob('SHARD_REGISTRY.json'))
    failures=[]
    if len(regs)!=EXPECTED_SHARDS: failures.append({'code':'SHARD_COUNT_MISMATCH','expected':EXPECTED_SHARDS,'observed':len(regs)})
    shard_indices=[]; player_ids=[]; all_segments=[]; all_recs=[]; shard_summary=[]
    for rp in regs:
        reg=load_json(rp); shard_indices.append(reg.get('shardIndex'))
        if reg.get('status')!='PASS': failures.append({'code':'SHARD_NOT_PASS','path':str(rp),'status':reg.get('status')})
        if reg.get('d1',{}).get('exactUnderstatAliases')!=EXPECTED_D1_ALIASES: failures.append({'code':'D1_ALIAS_COUNT_MISMATCH','path':str(rp),'count':reg.get('d1',{}).get('exactUnderstatAliases')})
        idx_path=rp.parent/'player-index.json'; seg_path=rp.parent/'segments.jsonl'; rec_path=rp.parent/'reconciliation.jsonl'
        for p in [idx_path,seg_path,rec_path]:
            if not p.exists(): failures.append({'code':'SHARD_FILE_MISSING','path':str(p)})
        if not idx_path.exists() or not seg_path.exists() or not rec_path.exists(): continue
        idx=load_json(idx_path); player_ids += [str(x['playerId']) for x in idx]; seg=list(load_jsonl(seg_path)); rec=list(load_jsonl(rec_path)); all_segments += seg; all_recs += rec
        shard_summary.append({'shardIndex':reg.get('shardIndex'),'playersExpected':reg.get('counts',{}).get('playersExpected'),'playersFetched':reg.get('counts',{}).get('playersFetched'),'sourceReferenceComparisons':len(rec),'segments':len(seg),'providerMatchRowsPreserved':reg.get('counts',{}).get('providerMatchRowsPreserved'),'referenceMatchRowsAssigned':reg.get('counts',{}).get('referenceMatchRowsAssigned'),'registrySha256':H(rp.read_bytes())})
    if sorted(shard_indices)!=list(range(EXPECTED_SHARDS)): failures.append({'code':'SHARD_INDEX_SET_INVALID','observed':sorted(shard_indices)})
    dup_players=[k for k,v in Counter(player_ids).items() if v!=1]
    if dup_players: failures.append({'code':'PLAYER_SHARD_ASSIGNMENT_NOT_UNIQUE','count':len(dup_players),'examples':dup_players[:20]})
    if len(player_ids)!=EXPECTED_D1_ALIASES: failures.append({'code':'FULL_PLAYER_COUNT_MISMATCH','expected':EXPECTED_D1_ALIASES,'observed':len(player_ids)})
    bad_recs=[r for r in all_recs if not r.get('allObservedFieldsExact')]
    if bad_recs: failures.append({'code':'RECONCILIATION_NOT_EXACT','count':len(bad_recs),'examples':bad_recs[:5]})
    rec_keys=[(r['playerId'],r['season'],r['league']) for r in all_recs]
    dup_recs=[k for k,v in Counter(rec_keys).items() if v!=1]
    if dup_recs: failures.append({'code':'RECONCILIATION_KEY_DUPLICATE','count':len(dup_recs),'examples':dup_recs[:20]})
    seg_keys=[(s['personKey'],s['season'],s['league'],s['segmentOrdinal']) for s in all_segments]
    dup_seg=[k for k,v in Counter(seg_keys).items() if v!=1]
    if dup_seg: failures.append({'code':'SEGMENT_KEY_DUPLICATE','count':len(dup_seg),'examples':dup_seg[:20]})
    impossible=[]
    for s in all_segments:
        o=s.get('observations',{}); games=o.get('games'); time=o.get('time'); goals=o.get('goals'); npg=o.get('npg')
        if games!=s.get('matchCount') or any((isinstance(v,(int,float)) and v<0) for v in o.values()) or (npg is not None and goals is not None and npg>goals): impossible.append({'playerId':s.get('playerId'),'season':s.get('season'),'league':s.get('league'),'segmentOrdinal':s.get('segmentOrdinal'),'observations':o,'matchCount':s.get('matchCount')})
    if impossible: failures.append({'code':'IMPOSSIBLE_SEGMENT_VALUES','count':len(impossible),'examples':impossible[:10]})
    by_league=Counter(s['league'] for s in all_segments); by_season=Counter(s['season'] for s in all_segments)
    file_manifest=[]
    for p in sorted(x for x in root.rglob('*') if x.is_file()):
        raw=p.read_bytes(); file_manifest.append({'path':str(p.relative_to(root)),'bytes':len(raw),'sha256':H(raw)})
    tree_digest=H('\n'.join(f"{x['path']}\t{x['sha256']}\t{x['bytes']}" for x in file_manifest).encode())
    status='PASS' if not failures else 'FAIL'
    audit={'schema':'NEXUS_F2_UNDERSTAT_FULL_TEMPORAL_RECONSTRUCTION_AUDIT_V1','status':status,'capturedAt':datetime.now(timezone.utc).isoformat(),'githubRunId':str(args.run_id),'sourceAuthority':{'d1Sha256':'952bdf1d4cfb81a0683bff1f78d949b6350b11be1cc27d20059f7ace651bb53c','understatAggregateSha256':'b78fad5f01844a0fdab0d89474dafba9b86c586d2f0ce88f0ce2c9af70d2bc64','provider':'UNDERSTAT','endpoint':'getPlayerData/{player_id}'},'counts':{'shards':len(regs),'d1ExactUnderstatPlayers':len(player_ids),'sourceReferenceComparisons':len(all_recs),'exactSourceReferenceComparisons':len(all_recs)-len(bad_recs),'observedClubSegments':len(all_segments),'rawFiles':sum(1 for x in file_manifest if '/raw/' in f"/{x['path']}"),'manifestFiles':len(file_manifest)},'segmentsByLeague':dict(sorted(by_league.items())),'segmentsBySeason':dict(sorted(by_season.items())),'validation':{'allD1AliasesFetchedExactlyOnce':len(player_ids)==EXPECTED_D1_ALIASES and not dup_players,'allSourceReferenceComparisonsExact':not bad_recs,'uniqueReconciliationKeys':not dup_recs,'uniqueSegmentKeys':not dup_seg,'impossibleValues':len(impossible),'fuzzyMatchingUsed':False,'expectedMetricsReleased':False,'aggregateUsedAsPrimaryEvidence':False,'canonicalPredictiveEngineModified':False},'shards':sorted(shard_summary,key=lambda x:x['shardIndex'] if x['shardIndex'] is not None else 999),'treeContentDigestSha256':tree_digest,'failures':failures,'temporalDecision':{'observedFields':['games','time','goals','npg','assists','shots','key_passes'],'releaseIfPass':'VERIFIED_EVENT_RECONSTRUCTION','expectedFields':['xG','npxG','xA','xGChain','xGBuildup'],'expectedFieldsStatus':'QUARANTINED_VINTAGE_REQUIRED'}}
    audit_meta=write_json(out/'FULL_AUDIT.json',audit)
    manifest={'schema':'NEXUS_F2_UNDERSTAT_FULL_TEMPORAL_RECONSTRUCTION_MANIFEST_V1','status':status,'githubRunId':str(args.run_id),'audit':audit_meta,'inputTreeContentDigestSha256':tree_digest,'inputFiles':file_manifest}
    manifest_meta=write_json(out/'MANIFEST.json',manifest)
    print(json.dumps({'status':status,'players':len(player_ids),'comparisons':len(all_recs),'segments':len(all_segments),'inputTreeDigest':tree_digest,'auditSha256':audit_meta['sha256'],'manifestSha256':manifest_meta['sha256'],'failures':len(failures)},indent=2))
    if status!='PASS': raise SystemExit(2)

if __name__=='__main__': main()
