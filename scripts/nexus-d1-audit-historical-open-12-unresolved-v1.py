#!/usr/bin/env python3
import json
from collections import Counter
from pathlib import Path
SRC1=Path('data/nexus-d1/historical-open-fantacalcio-v1/RESULT.json');SRC2=Path('data/nexus-d1/historical-open-fantacalcio-v2/RESULT.json');OUT=Path('data/nexus-d1/historical-open-12-unresolved-audit-v1')
def main():
 v1=json.loads(SRC1.read_text());v2=json.loads(SRC2.read_text());by={r['subjectId']:r for r in v1['records']};rem=[r for r in v2['records'] if r['status']=='DOB_UNRESOLVED_NO_ACCEPTED_EXACT_FC_OBSERVATION'];assert len(rem)==12
 out=[];globalc=Counter()
 for r in rem:
  old=by[r['subjectId']];c=Counter(a.get('status') for a in old.get('attempts') or []);globalc.update(c)
  useful=[]
  for a in old.get('attempts') or []:
   if a.get('httpStatus')==200:
    useful.append({'fantacalcioPlayerId':a.get('fantacalcioPlayerId'),'season':a.get('season'),'status':a.get('status'),'exactSeasonPlayerIdBound':a.get('exactSeasonPlayerIdBound'),'fullName':a.get('fullName'),'dobCandidates':a.get('dobCandidates'),'rawPath':a.get('rawPath'),'canonicalUrl':a.get('canonicalUrl')})
  out.append({'subjectId':r['subjectId'],'understatPlayerId':r['understatPlayerId'],'lookupNames':r.get('lookupNames'),'attemptStatusCounts':dict(sorted(c.items())),'http200Attempts':useful})
 result={'schema':'NEXUS_D1_HISTORICAL_OPEN_12_UNRESOLVED_AUDIT_V1','status':'PASS','subjects':12,'aggregateAttemptStatusCounts':dict(sorted(globalc.items())),'records':out,'governance':{'ruleChanged':False,'networkRequestsMade':0,'rawMutated':False,'fuzzyMatchingUsed':False,'f1Started':False,'d2Started':False}}
 OUT.mkdir(parents=True,exist_ok=True);(OUT/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'subjects':12,'aggregateAttemptStatusCounts':result['aggregateAttemptStatusCounts'],'records':[{'subjectId':x['subjectId'],'understatPlayerId':x['understatPlayerId'],'lookupNames':x['lookupNames'],'attemptStatusCounts':x['attemptStatusCounts'],'http200':[{'id':a['fantacalcioPlayerId'],'season':a['season'],'status':a['status'],'fullName':a['fullName'],'dob':a['dobCandidates']} for a in x['http200Attempts']]} for x in out]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
