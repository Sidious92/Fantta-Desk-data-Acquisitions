#!/usr/bin/env python3
import hashlib,html,json,re,unicodedata
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
SRC=Path('data/nexus-d1/historical-open-fantacalcio-v1/RESULT.json');OUT=Path('data/nexus-d1/historical-open-fantacalcio-v2')
def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b):return hashlib.sha256(b).hexdigest()
def toks(s):
 s=html.unescape(str(s));s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower();return set(x for x in re.split(r'[^a-z0-9]+',s) if x)
def main():
 b=SRC.read_bytes();d=json.loads(b);assert d['status']=='PASS' and d['summary']['subjects']==109 and d['summary']['requestFailures']==0
 rows=[]
 for r in d['records']:
  lookup_sets=[toks(x) for x in r.get('lookupNames') or [] if toks(x)];accepted=[]
  for a in r.get('attempts') or []:
   full=toks(a.get('fullName') or ''); dates=a.get('dobCandidates') or []
   nameok=bool(full) and any(ls.issubset(full) for ls in lookup_sets)
   keyok=a.get('exactSeasonPlayerIdBound') is True
   if keyok and nameok and len(dates)==1:
    accepted.append({'fantacalcioPlayerId':a.get('fantacalcioPlayerId'),'season':a.get('season'),'fullName':a.get('fullName'),'dateOfBirth':dates[0],'rawPath':a.get('rawPath'),'rawSha256':a.get('rawSha256'),'canonicalUrl':a.get('canonicalUrl'),'exactSeasonPlayerIdBound':True,'lookupNameTokenSubsetOfFullName':True})
  vals=sorted({x['dateOfBirth'] for x in accepted})
  if len(vals)==1:st='HISTORICAL_PERSON_DOB_VERIFIED_BY_EXACT_FC_OBSERVATION'
  elif len(vals)>1:st='DOB_CONFLICT_ACROSS_EXACT_FC_OBSERVATIONS'
  else:st='DOB_UNRESOLVED_NO_ACCEPTED_EXACT_FC_OBSERVATION'
  rows.append({'subjectId':r['subjectId'],'bridgePersonKey':r['bridgePersonKey'],'understatPlayerId':r['understatPlayerId'],'lookupNames':r.get('lookupNames'),'status':st,'dateOfBirth':vals[0] if len(vals)==1 else None,'distinctAcceptedDobValues':vals,'acceptedObservationCount':len(accepted),'acceptedObservations':accepted,'priorV1Status':r.get('status')})
 c=Counter(x['status'] for x in rows);status='PASS';cap=now()
 result={'schema':'NEXUS_D1_HISTORICAL_OPEN_FANTACALCIO_DEMOGRAPHICS_RESULT_V2','protocolVersion':'1.1','status':status,'capturedAt':cap,'derivation':{'sourceV1Path':str(SRC),'sourceV1Bytes':len(b),'sourceV1Sha256':sha(b),'networkRequestsMade':0,'rawEvidenceReusedWithoutMutation':True,'personBridgeAuthority':'D0_DERIVED_UNDERSTAT_BACKED_PERSON_SURFACE','reviewChange':'Exact D0 lookup-name token set may be a subset of the exact Fantacalcio full-name token set on an exact season+playerId observation.'},'rules':{'providerObservationKey':['Fantacalcio','season','fantacalcioPlayerId'],'providerIdUsedAsGlobalHistoricalPersonKey':False,'d0UnderstatPersonBridgeRequired':True,'exactSeasonPlayerIdCanonicalBindingRequired':True,'exactLookupTokenSubsetOfFullNameRequired':True,'nameSearchUsed':False,'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'computedAgeDerived':False,'currentRetrievalImpliesHistoricalAsOf':False,'f1Started':False,'d2Started':False},'summary':{'subjects':109,'statusCounts':dict(sorted(c.items())),'dobVerifiedSubjects':c.get('HISTORICAL_PERSON_DOB_VERIFIED_BY_EXACT_FC_OBSERVATION',0),'dobConflictSubjects':c.get('DOB_CONFLICT_ACROSS_EXACT_FC_OBSERVATIONS',0),'unresolvedSubjects':c.get('DOB_UNRESOLVED_NO_ACCEPTED_EXACT_FC_OBSERVATION',0)},'records':rows}
 OUT.mkdir(parents=True,exist_ok=True);rb=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'RESULT.json').write_bytes(rb);(OUT/'MANIFEST.json').write_text(json.dumps({'schema':'NEXUS_D1_HISTORICAL_OPEN_FANTACALCIO_DEMOGRAPHICS_MANIFEST_V2','status':'PASS','resultBytes':len(rb),'resultSha256':sha(rb),'rawEvidenceAuthority':'data/nexus-d1/historical-open-fantacalcio-v1/MANIFEST.json','governance':result['rules']},indent=2)+'\n');print(json.dumps(result['summary'],indent=2))
if __name__=='__main__':main()
