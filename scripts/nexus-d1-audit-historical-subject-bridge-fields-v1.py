#!/usr/bin/env python3
import base64,hashlib,json,lzma
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path

MAN=Path('data/nexus-d1/historical-resolved-person-subjects-v3-manifest.json')
OPEN=Path('data/nexus-d1/second-pass-v2/SECOND_PASS_SUBJECTS.json')
OUT=Path('data/nexus-d1/historical-subject-bridge-audit-v1')

def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def main():
 m=json.loads(MAN.read_text()); parts=[]
 for c in m['payload']['chunks']:
  t=Path(c['path']).read_text().strip(); assert len(t)==c['chars']; assert hashlib.sha256(t.encode()).hexdigest()==c['textSha256']; parts.append(t)
 raw=lzma.decompress(base64.b64decode(''.join(parts),validate=True)); assert hashlib.sha256(raw).hexdigest()==m['payload']['decodedJsonSha256']
 d=json.loads(raw); subjects=d['subjects']; by={str(s['understatPlayerId']):s for s in subjects}
 sp=json.loads(OPEN.read_text()); rows=[r for r in sp['historicalOpen'] if r.get('mappingStatus')!='IDENTITY_VERIFIED']
 ids=[]
 for r in rows:
  b=r.get('bridgePersonKey') or ''
  ids.append(b.split(':',1)[1] if b.startswith('understat:') else str(r.get('understatPlayerId') or ''))
 assert len(rows)==109 and all(i in by for i in ids)
 key_counts=Counter(); nested_counts=Counter(); samples=[]
 for i in ids:
  s=by[i]
  for k in s:key_counts[k]+=1
  for k,v in s.items():
   if isinstance(v,list) and v and isinstance(v[0],dict):
    for nk in v[0]:nested_counts[f'{k}[].{nk}']+=1
  if len(samples)<5:samples.append({'understatPlayerId':i,'keys':sorted(s.keys()),'subject':s})
 result={'schema':'NEXUS_D1_HISTORICAL_SUBJECT_BRIDGE_FIELD_AUDIT_V1','status':'PASS','capturedAt':now(),'historicalIdentityProblemSubjects':109,'subjectTopLevelKeyPresence':dict(sorted(key_counts.items())),'nestedFirstItemKeyPresence':dict(sorted(nested_counts.items())),'samples':samples,'governance':{'performanceStatisticsConsumed':False,'fuzzyMatchingUsed':False,'d2Started':False,'f1Started':False}}
 OUT.mkdir(parents=True,exist_ok=True); (OUT/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n'); print(json.dumps({'subjects':109,'topLevelKeys':result['subjectTopLevelKeyPresence'],'nestedKeys':result['nestedFirstItemKeyPresence']},indent=2))
if __name__=='__main__':main()
