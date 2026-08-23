#!/usr/bin/env python3
import argparse, hashlib, json
from pathlib import Path

def H(b): return hashlib.sha256(b).hexdigest()
def read_json(p): return json.loads(p.read_text(encoding='utf-8'))
def read_jsonl(p): return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]
def write_json(p,o):
    raw=(json.dumps(o,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode(); p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(raw); return {'path':str(p),'bytes':len(raw),'sha256':H(raw)}
def write_jsonl(p,rows):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('w',encoding='utf-8',newline='\n') as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    raw=p.read_bytes(); return {'path':str(p),'bytes':len(raw),'rows':len(rows),'sha256':H(raw)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--input-root',required=True); ap.add_argument('--output-root',required=True); ap.add_argument('--run-id',required=True); a=ap.parse_args()
    root=Path(a.input_root); out=Path(a.output_root); out.mkdir(parents=True,exist_ok=True)
    regs=sorted(root.rglob('SHARD_REGISTRY.json'))
    shards=[]; labels=[]; dups=[]; qa=[]; failures=[]
    for rp in regs:
        reg=read_json(rp); shards.append(reg)
        base=rp.parent
        labels.extend(read_jsonl(base/'labels.jsonl')); dups.extend(read_jsonl(base/'duplicates.jsonl')); qa.extend(read_jsonl(base/'qa.jsonl'))
        if reg.get('status')!='PASS': failures.append({'code':'SHARD_NOT_PASS','shard':reg.get('shardIndex'),'status':reg.get('status')})
        if reg.get('failures'): failures.append({'code':'SHARD_FAILURES_NONEMPTY','shard':reg.get('shardIndex'),'count':len(reg['failures'])})
    ids=[str(x['playerId']) for x in labels]; unique_ids=set(ids)
    if len(regs)!=4: failures.append({'code':'SHARD_COUNT','expected':4,'actual':len(regs)})
    if len(labels)!=451: failures.append({'code':'LABEL_COUNT','expected':451,'actual':len(labels)})
    if len(unique_ids)!=len(ids): failures.append({'code':'DUPLICATE_PLAYER_LABELS','duplicates':len(ids)-len(unique_ids)})
    observed=[x for x in labels if x.get('status')=='OBSERVED']; missing=[x for x in labels if x.get('status')=='MISSING']
    unexpected=[x for x in labels if x.get('status') not in ('OBSERVED','MISSING')]
    if unexpected: failures.append({'code':'UNKNOWN_LABEL_STATUS','count':len(unexpected)})
    group_counts={}
    for x in labels: group_counts[x.get('groupsQaStatus')]=group_counts.get(x.get('groupsQaStatus'),0)+1
    missing_reasons={}
    for x in missing: missing_reasons[x.get('missingReason')]=missing_reasons.get(x.get('missingReason'),0)+1
    labels=sorted(labels,key=lambda x:int(x['playerId'])); dups=sorted(dups,key=lambda x:(int(x['playerId']),str(x['matchId']))); qa=sorted(qa,key=lambda x:int(x['playerId']))
    files={'labels':write_jsonl(out/'labels-2025-26.jsonl',labels),'duplicates':write_jsonl(out/'duplicate-technical-events.jsonl',dups),'qa':write_jsonl(out/'groups-qa.jsonl',qa)}
    status='PASS' if not failures else 'FAIL'
    audit={'schema':'NEXUS_F2B_2025_26_EVENT_LABEL_EXTENSION_AUDIT_V1','status':status,'runId':a.run_id,'counts':{'shards':len(regs),'targetPlayers':451,'labels':len(labels),'observedLabels':len(observed),'missingLabels':len(missing),'duplicateTechnicalGroups':len(dups)},'groupsQaStatusCounts':group_counts,'missingReasonCounts':missing_reasons,'files':files,'failures':failures,'governance':{'eventLevelPrimaryAuthority':True,'retrospectiveAggregatePrimaryAuthority':False,'expectedMetricsReleased':False,'fuzzyMatchingUsed':False,'canonicalPredictiveEngineModified':False}}
    write_json(out/'FULL_AUDIT.json',audit)
    manifest={'schema':'NEXUS_F2B_2025_26_EVENT_LABEL_EXTENSION_MANIFEST_V1','runId':a.run_id,'auditStatus':status,'auditSha256':H((out/'FULL_AUDIT.json').read_bytes()),'files':files}
    write_json(out/'MANIFEST.json',manifest); print(json.dumps(audit,indent=2))
    if status!='PASS': raise SystemExit(2)

if __name__=='__main__': main()
