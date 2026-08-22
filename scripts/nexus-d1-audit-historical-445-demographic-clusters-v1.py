#!/usr/bin/env python3
import json,re,hashlib,unicodedata
from collections import defaultdict,Counter
from pathlib import Path
from datetime import datetime,timezone
SRC=Path('.nexus-d1-historical-445-observation-demographics-v1-status/RESULT.json')
OUT=Path('data/nexus-d1/historical-445-demographic-cluster-audit-v1'); OUT.mkdir(parents=True,exist_ok=True)
def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def norm_tokens(s):
    s=unicodedata.normalize('NFKC',s or '').casefold().replace('’',"'")
    return tuple(sorted(re.findall(r"[\w]+",s,flags=re.UNICODE)))
def sig(r): return {'nameTokens':norm_tokens(r.get('fullName')),'dateOfBirth':r.get('dateOfBirth')}
s=json.loads(SRC.read_text()); assert s['status']=='PASS' and s['scope']['auditSubjectGroups']==445 and s['scope']['providerObservations']==704
groups=defaultdict(list)
for r in s['records']: groups[r['sourceSubjectIndex']].append(r)
if len(groups)!=445: raise SystemExit(f'EXPECTED_445_GOT_{len(groups)}')
out=[]; counts=Counter()
for idx in sorted(groups):
    recs=groups[idx]; verified=[r for r in recs if r.get('status')=='OBSERVATION_DEMOGRAPHICS_VERIFIED']
    signatures={ (norm_tokens(r.get('fullName')),r.get('dateOfBirth')) for r in verified }
    if len(signatures)==1:
        status='SINGLE_EXACT_DEMOGRAPHIC_SIGNATURE'
    elif len(signatures)>1:
        status='MULTIPLE_EXACT_DEMOGRAPHIC_SIGNATURES'
    else:
        status='NO_VERIFIED_DEMOGRAPHIC_SIGNATURE'
    counts[status]+=1
    out.append({'sourceSubjectIndex':idx,'fantacalcioPlayerId':recs[0].get('fantacalcioPlayerId'),'providerIdReuseOrNameVariationFlag':bool(recs[0].get('providerIdReuseOrNameVariationFlag')),'observationCount':len(recs),'verifiedObservationCount':len(verified),'failedObservationCount':len(recs)-len(verified),'status':status,'signatures':[{'nameTokens':list(a),'dateOfBirth':b} for a,b in sorted(signatures)],'personMergePerformed':False})
res={'schema':'NEXUS_D1_HISTORICAL_445_DEMOGRAPHIC_CLUSTER_AUDIT_V1','protocolVersion':'1.1','status':'PASS','capturedAt':now(),'rules':{'scopeWithinFantacalcioAuditIdOnly':True,'crossProviderIdMergeUsed':False,'providerIdUsedAsGlobalPersonKey':False,'signatureUsesExactNormalizedFullNameTokensAndDayDob':True,'fuzzyMatchingUsed':False,'personMergePerformed':False,'computedAgeDerived':False,'f1Started':False,'d2Started':False},'summary':{'groups':445,'observations':704,'statusCounts':dict(sorted(counts.items())),'groupsWithProviderReuseOrNameVariationFlag':sum(x['providerIdReuseOrNameVariationFlag'] for x in out)},'groups':out}
b=(json.dumps(res,ensure_ascii=False,indent=2)+'\n').encode(); (OUT/'RESULT.json').write_bytes(b); (OUT/'MANIFEST.json').write_text(json.dumps({'schema':'NEXUS_D1_HISTORICAL_445_DEMOGRAPHIC_CLUSTER_AUDIT_MANIFEST_V1','status':'PASS','resultBytes':len(b),'resultSha256':hashlib.sha256(b).hexdigest(),'governance':res['rules']},indent=2)+'\n'); print(json.dumps(res['summary'],indent=2))