#!/usr/bin/env python3
import hashlib,json
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

SRC=Path('data/nexus-d1/second-pass-v2/SECOND_PASS_SUBJECTS.json')
OUT=Path('data/nexus-d1/second-pass-routing-audit-v1')

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b): return hashlib.sha256(b).hexdigest()
def understat_id(r):
    b=r.get('bridgePersonKey')
    if isinstance(b,str) and b.startswith('understat:') and b.split(':',1)[1]: return b.split(':',1)[1]
    u=r.get('understatPlayerId')
    return str(u) if u not in (None,'') else None

def classify(rows):
    ident=[r for r in rows if r.get('mappingStatus')!='IDENTITY_VERIFIED']
    conflict=[r for r in rows if r.get('mappingStatus')=='IDENTITY_VERIFIED' and r.get('dateOfBirthStatus')=='DOB_CONFLICT']
    with_u=[r for r in ident if understat_id(r)]
    without_u=[r for r in ident if not understat_id(r)]
    return {
      'records':len(rows),'identityProblemRecords':len(ident),'verifiedIdentityDobConflictRecords':len(conflict),
      'identityProblemWithExactUnderstatBridge':len(with_u),'identityProblemWithoutExactUnderstatBridge':len(without_u),
      'identityProblemMappingStatus':dict(sorted(Counter(r.get('mappingStatus') for r in ident).items())),
      'exactUnderstatIds':len({understat_id(r) for r in with_u}),
    }

def main():
    b=SRC.read_bytes(); d=json.loads(b)
    if d.get('status')!='PASS': raise RuntimeError('SECOND_PASS_V2_NOT_PASS')
    cur=d['currentOpen']; hist=d['historicalOpen']
    result={'schema':'NEXUS_D1_SECOND_PASS_ROUTING_AUDIT_V1','protocolVersion':'1.1','status':'PASS','capturedAt':now(),'source':{'path':str(SRC),'bytes':len(b),'sha256':sha(b)},'current':classify(cur),'historical':classify(hist),'combined':classify(cur+hist),'historicalNeverResolvedFantacalcioSublot':{'uniqueProviderIds':445,'observations':704,'authority':'data/nexus-d1/historical-never-resolved-fantacalcio-ids-v1-manifest.json','separateFromResolvedPersonSecondPass':True},'governance':{'providerIdUsedAsGlobalPersonKey':False,'nameOnlyMergeUsed':False,'fuzzyMatchingUsed':False,'dobInferred':False,'computedAgeDerived':False,'f1Started':False,'d2Started':False}}
    assert result['combined']['records']==282
    assert result['combined']['identityProblemRecords']==235
    assert result['combined']['verifiedIdentityDobConflictRecords']==47
    OUT.mkdir(parents=True,exist_ok=True)
    rb=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode(); (OUT/'RESULT.json').write_bytes(rb)
    (OUT/'MANIFEST.json').write_text(json.dumps({'schema':'NEXUS_D1_SECOND_PASS_ROUTING_AUDIT_MANIFEST_V1','status':'PASS','resultBytes':len(rb),'resultSha256':sha(rb),'governance':result['governance']},indent=2)+'\n')
    print(json.dumps({'status':'PASS','current':result['current'],'historical':result['historical'],'combined':result['combined']},indent=2))
if __name__=='__main__': main()
