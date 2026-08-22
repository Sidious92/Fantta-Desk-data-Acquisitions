#!/usr/bin/env python3
import json, hashlib, re
from pathlib import Path
from datetime import datetime, timezone

OPEN=Path('data/nexus-d1/historical-open-fantacalcio-v1/RESULT.json')
OPEN2=Path('data/nexus-d1/historical-open-fantacalcio-v2/RESULT.json')
CONF=Path('data/nexus-d1/historical-dob-conflict-fantacalcio-v1/RESULT.json')
OUT=Path('data/nexus-d1/historical-residual-review-v1')
OUT.mkdir(parents=True, exist_ok=True)

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b): return hashlib.sha256(b).hexdigest()

def exact_dobs(attempts):
    vals=[]
    used=[]
    for a in attempts or []:
        if a.get('httpStatus')==200 and a.get('exactSeasonPlayerIdBound') is True:
            ds=a.get('dobCandidates') or []
            if len(ds)==1 and re.fullmatch(r'\d{4}-\d{2}-\d{2}',ds[0]):
                vals.append(ds[0]); used.append(a)
    return sorted(set(vals)), used

v1=json.loads(OPEN.read_text())
v2=json.loads(OPEN2.read_text())
cf=json.loads(CONF.read_text())
if v1.get('status')!='PASS' or v2.get('status')!='PASS' or cf.get('status')!='PASS': raise SystemExit('SOURCE_NOT_PASS')

v1_by={r['subjectId']:r for r in v1['records']}
open_out=[]
for r in v2['records']:
    if r['status']!='DOB_UNRESOLVED_NO_ACCEPTED_EXACT_FC_OBSERVATION': continue
    src=v1_by[r['subjectId']]
    vals,used=exact_dobs(src.get('attempts'))
    status='HISTORICAL_PERSON_DOB_VERIFIED_BY_D0_BRIDGE_AND_EXACT_FC_CONSENSUS' if len(vals)==1 else ('DOB_CONFLICT_MULTIPLE_EXACT_FC_VALUES' if len(vals)>1 else 'DOB_UNRESOLVED_NO_EXACT_FC_DOB')
    open_out.append({'subjectId':r['subjectId'],'understatPlayerId':r.get('understatPlayerId'),'bridgePersonKey':r.get('bridgePersonKey'),'status':status,'dateOfBirth':vals[0] if len(vals)==1 else None,'exactDobValues':vals,'exactObservationCount':len(used),'identityAuthority':'D0_DERIVED_UNDERSTAT_PERSON_BRIDGE','nameGateUsed':False})

conf_out=[]
for r in cf['records']:
    if r['status']!='DOB_CONFLICT_UNRESOLVED_NO_ACCEPTED_FC_OBSERVATION': continue
    vals,used=exact_dobs(r.get('attempts'))
    existing=set(r.get('existingConflictDates') or [])
    matching=[d for d in vals if d in existing]
    status='DOB_CONFLICT_RESOLVED_BY_D0_BRIDGE_AND_EXACT_FC_CONSENSUS' if len(vals)==1 and len(matching)==1 else 'DOB_CONFLICT_REMAINS_UNRESOLVED'
    conf_out.append({'subjectId':r['subjectId'],'understatPlayerId':r.get('understatPlayerId'),'wikidataItemId':r.get('wikidataItemId'),'existingConflictDates':sorted(existing),'exactFantacalcioDobValues':vals,'matchingExistingConflictDates':matching,'status':status,'dateOfBirth':matching[0] if status.startswith('DOB_CONFLICT_RESOLVED') else None,'exactObservationCount':len(used),'identityAuthority':'VERIFIED_WIKIDATA_QID_PLUS_D0_UNDERSTAT_PERSON_BRIDGE','nameGateUsed':False})

res={'schema':'NEXUS_D1_HISTORICAL_RESIDUAL_REVIEW_V1','protocolVersion':'1.1','status':'PASS','capturedAt':now(),'rules':{'networkRequestsMade':0,'rawEvidenceMutated':False,'d0PersonBridgeIsIdentityAuthority':True,'providerObservationKey':['Fantacalcio','season','fantacalcioPlayerId'],'providerIdUsedAsGlobalHistoricalPersonKey':False,'nameSearchUsed':False,'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'computedAgeDerived':False,'f1Started':False,'d2Started':False},'summary':{'historicalOpenResidualSubjects':len(open_out),'historicalOpenResolved':sum(x['dateOfBirth'] is not None for x in open_out),'historicalDobConflictResidualSubjects':len(conf_out),'historicalDobConflictsResolved':sum(x['dateOfBirth'] is not None for x in conf_out)},'historicalOpenResiduals':open_out,'historicalDobConflictResiduals':conf_out}
b=json.dumps(res,ensure_ascii=False,indent=2).encode()+b'\n'; (OUT/'RESULT.json').write_bytes(b)
man={'schema':'NEXUS_D1_HISTORICAL_RESIDUAL_REVIEW_MANIFEST_V1','status':'PASS','resultBytes':len(b),'resultSha256':sha(b),'governance':res['rules']}; (OUT/'MANIFEST.json').write_text(json.dumps(man,indent=2)+'\n')
print(json.dumps(res['summary'],indent=2))