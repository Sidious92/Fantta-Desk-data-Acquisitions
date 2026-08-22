#!/usr/bin/env python3
import base64,hashlib,json,lzma
from datetime import datetime,timezone
from pathlib import Path
M=Path('data/nexus-d1/historical-never-resolved-fantacalcio-ids-v1-manifest.json');P=Path('data/nexus-d1/historical-never-resolved-fantacalcio-ids-v1.json.xz.b64');O=Path('data/nexus-d1/historical-never-resolved-schema-audit-v1')
def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def main():
 m=json.loads(M.read_text());enc=P.read_text().strip();xz=base64.b64decode(enc,validate=True);raw=lzma.decompress(xz)
 assert len(enc)==m['payload']['base64Chars'];assert len(xz)==m['payload']['xzBytes'];assert hashlib.sha256(xz).hexdigest()==m['payload']['xzSha256'];assert len(raw)==m['payload']['decodedJsonBytes'];assert hashlib.sha256(raw).hexdigest()==m['payload']['decodedJsonSha256']
 d=json.loads(raw)
 r={'schema':'NEXUS_D1_HISTORICAL_NEVER_RESOLVED_SUBLOT_SCHEMA_AUDIT_V1','status':'PASS','capturedAt':now(),'rootType':type(d).__name__,'rootKeys':sorted(d.keys()) if isinstance(d,dict) else None}
 if isinstance(d,dict):
  for k,v in d.items():
   if isinstance(v,list):
    r.setdefault('listFields',{})[k]={'length':len(v),'firstItemType':type(v[0]).__name__ if v else None,'firstItemKeys':sorted(v[0].keys()) if v and isinstance(v[0],dict) else None,'firstItem':v[0] if v else None}
 r['governance']={'payloadMutated':False,'performanceStatisticsConsumed':False,'f1Started':False,'d2Started':False}
 O.mkdir(parents=True,exist_ok=True);(O/'RESULT.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n');print(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
