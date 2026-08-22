#!/usr/bin/env python3
import hashlib,json,re
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
SRC=Path('data/nexus-d1/current-open-fantacalcio-v1/RESULT.json');PROBE=Path('data/nexus-d1/fantacalcio-current-exact-id-probe-v1/RESULT.json');OUT=Path('data/nexus-d1/current-open-fantacalcio-v2')
def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b):return hashlib.sha256(b).hexdigest()
def main():
 pb=json.loads(PROBE.read_text());assert pb['status']=='PASS' and pb['summary']['exactIdDobPass']==4
 sb=SRC.read_bytes();d=json.loads(sb);assert d['status']=='PASS' and d['summary']['subjects']==127 and d['summary']['requestFailures']==0
 rows=[]
 for r in d['records']:
  sid=str(r['subjectId']);m=re.fullmatch(r'current-fc-(\d+)',sid);pid=str(r['fantacalcioPlayerId'])
  sidok=bool(m and m.group(1)==pid);dates=r.get('dobCandidates') or [];ok=sidok and r.get('exactProviderIdBound') is True and bool(r.get('fullName')) and len(dates)==1
  rows.append({'subjectId':sid,'fantacalcioPlayerId':pid,'status':'CURRENT_IDENTITY_DOB_VERIFIED' if ok else 'REVIEW_REQUIRED','fullName':r.get('fullName'),'dateOfBirth':dates[0] if ok else None,'sourceRawPath':r.get('rawPath'),'sourceRawSha256':r.get('rawSha256'),'sourceCanonicalUrl':r.get('canonicalUrl'),'checks':{'subjectIdMatchesExactProviderId':sidok,'exactProviderIdBound':r.get('exactProviderIdBound'),'fullNamePresent':bool(r.get('fullName')),'singleDayPrecisionDob':len(dates)==1},'priorClubProximityFlag':r.get('expectedClubConfirmedNearIdentity')})
 c=Counter(x['status'] for x in rows);status='PASS' if len(rows)==127 and c.get('CURRENT_IDENTITY_DOB_VERIFIED',0)==127 else 'REVIEW_REQUIRED';cap=now()
 result={'schema':'NEXUS_D1_CURRENT_OPEN_FANTACALCIO_DEMOGRAPHICS_RESULT_V2','protocolVersion':'1.1','status':status,'capturedAt':cap,'derivation':{'sourceV1Path':str(SRC),'sourceV1Bytes':len(sb),'sourceV1Sha256':sha(sb),'networkRequestsMade':0,'rawEvidenceReusedWithoutMutation':True,'clubProximityGateRemovedReason':'Current subject is already bound to the canonical current Listone Fantacalcio playerId; club text proximity is not part of the provider observation key.'},'rules':{'currentProviderObservationKey':['Fantacalcio','currentListoneAsOf2026-08-18','fantacalcioPlayerId'],'providerIdUsedAsGlobalHistoricalPersonKey':False,'exactProviderIdBindingRequired':True,'fullNameRequired':True,'singleDayPrecisionDobRequired':True,'nameSearchUsed':False,'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'computedAgeDerived':False,'f1Started':False,'d2Started':False},'summary':{'subjects':127,'statusCounts':dict(sorted(c.items())),'currentIdentityDobVerified':c.get('CURRENT_IDENTITY_DOB_VERIFIED',0)},'records':rows}
 OUT.mkdir(parents=True,exist_ok=True);rb=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'RESULT.json').write_bytes(rb);(OUT/'MANIFEST.json').write_text(json.dumps({'schema':'NEXUS_D1_CURRENT_OPEN_FANTACALCIO_DEMOGRAPHICS_MANIFEST_V2','status':status,'resultBytes':len(rb),'resultSha256':sha(rb),'rawEvidenceAuthority':'data/nexus-d1/current-open-fantacalcio-v1/MANIFEST.json','governance':result['rules']},indent=2)+'\n');print(json.dumps(result['summary'],indent=2))
 if status!='PASS':raise SystemExit(2)
if __name__=='__main__':main()
