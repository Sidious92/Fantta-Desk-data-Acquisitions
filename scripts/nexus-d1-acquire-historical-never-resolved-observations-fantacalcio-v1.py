#!/usr/bin/env python3
from __future__ import annotations
import argparse,base64,hashlib,html,json,lzma,re,time,traceback,unicodedata
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen

UA='Mozilla/5.0 FantaNexus-D1/1.1 private-scientific-audit'
RETRYABLE={429,500,502,503,504}
MONTHS={'gen':1,'feb':2,'mar':3,'apr':4,'mag':5,'giu':6,'lug':7,'ago':8,'set':9,'ott':10,'nov':11,'dic':12}

def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b):return hashlib.sha256(b).hexdigest()
def clean(s):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def norm_tokens(s):
 s=html.unescape(str(s));s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower();return tuple(sorted(x for x in re.split(r'[^a-z0-9]+',s) if x))
def fetch(u,attempts=8):
 last=None
 for i in range(attempts):
  try:
   req=Request(u,headers={'User-Agent':UA,'Accept':'text/html,*/*;q=0.8','Accept-Language':'it-IT,it;q=0.9,en;q=0.7'})
   with urlopen(req,timeout=45) as r:return r.status,dict(r.headers.items()),r.read(),r.geturl()
  except HTTPError as e:
   if e.code==404:return 404,dict(e.headers.items()) if e.headers else {},e.read(),u
   last=e
   if e.code not in RETRYABLE:raise
  except (URLError,TimeoutError) as e:last=e
  time.sleep(min(30,1.5*(2**i)))
 raise last
def h1(t):
 m=re.search(r'<h1[^>]*>(.*?)</h1>',t,re.I|re.S);return clean(m.group(1)) if m else None
def canonical(t):
 for p in [r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']']:
  m=re.search(p,t,re.I)
  if m:return html.unescape(m.group(1))
def dob(t):
 vals=set();plain=clean(t)
 for d,m,y in re.findall(r'\bNato\s+il\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]{3,10})\s+(\d{4})\b',plain,re.I):
  k=unicodedata.normalize('NFKD',m).encode('ascii','ignore').decode().lower()[:3]
  if k in MONTHS:vals.add(f'{int(y):04d}-{MONTHS[k]:02d}-{int(d):02d}')
 return sorted(vals)
def load_surface(manifest,payload):
 m=json.loads(Path(manifest).read_text());enc=Path(payload).read_text().strip();xz=base64.b64decode(enc,validate=True);raw=lzma.decompress(xz)
 assert len(enc)==m['payload']['base64Chars'];assert len(xz)==m['payload']['xzBytes'];assert sha(xz)==m['payload']['xzSha256'];assert len(raw)==m['payload']['decodedJsonBytes'];assert sha(raw)==m['payload']['decodedJsonSha256']
 return json.loads(raw),m
def flatten(d):
 rows=[]
 for si,s in enumerate(d['subjects']):
  pid=str(s['fantacalcioSourcePlayerId']);names=[str(x) for x in s.get('exactObservedNames') or []];flag=bool(s.get('providerIdReuseOrNameVariationFlag'))
  for oi,o in enumerate(s.get('observations') or []):
   rows.append({'globalIndex':len(rows),'sourceSubjectIndex':si,'sourceObservationIndex':oi,'fantacalcioPlayerId':pid,'subjectAuditNames':names,'providerIdReuseOrNameVariationFlag':flag,'season':str(o['season']),'seasonStart':o.get('seasonStart'),'observedName':str(o['name']),'teamCode':str(o.get('team') or '')})
 return rows

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--manifest',required=True);ap.add_argument('--payload',required=True);ap.add_argument('--probe',required=True);ap.add_argument('--output',required=True);ap.add_argument('--start',type=int,required=True);ap.add_argument('--end',type=int,required=True);a=ap.parse_args()
 probe=json.loads(Path(a.probe).read_text());assert probe['status']=='PASS';assert probe['semantics']['neutralSeoSlugsAccepted'] is True;assert probe['semantics']['providerIdUsedAsGlobalPersonKey'] is False
 d,m=load_surface(a.manifest,a.payload);assert len(d['subjects'])==445;rows=flatten(d);assert len(rows)==704
 sel=rows[a.start:a.end];out=Path(a.output);raw=out/'raw';raw.mkdir(parents=True,exist_ok=True);recs=[];fails=[]
 for r in sel:
  season_slug=r['season'].replace('/','-');pid=r['fantacalcioPlayerId'];u=f'https://www.fantacalcio.it/serie-a/squadre/x/x/{pid}/{season_slug}'
  rec={**r,'providerObservationKey':{'provider':'Fantacalcio','season':r['season'],'fantacalcioPlayerId':pid},'providerObservationKeyIsGlobalPersonKey':False,'requestedUrl':u}
  try:
   st,h,b,fu=fetch(u);rec['httpStatus']=st
   if st==404:
    rec['status']='SOURCE_NO_COVERAGE_OBSERVATION_PAGE';recs.append(rec);continue
   p=raw/f"{r['globalIndex']:04d}--fc{pid}--{season_slug}.html";p.write_bytes(b);t=b.decode('utf-8',errors='replace');can=canonical(t);nm=h1(t);dates=dob(t);bind=('/'+pid+'/') in ((can or fu)+'/') and season_slug in (can or fu)
   observed_tokens=set(norm_tokens(r['observedName']));full_tokens=set(norm_tokens(nm or ''));name_consistent=bool(observed_tokens) and observed_tokens.issubset(full_tokens)
   rec.update({'finalUrl':fu,'canonicalUrl':can,'exactSeasonPlayerIdBound':bind,'fullName':nm,'dobCandidates':dates,'observedNameTokensSubsetOfFullName':name_consistent,'rawPath':str(p.relative_to(out)),'rawBytes':len(b),'rawSha256':sha(b)})
   if not bind:rec['status']='OBSERVATION_BINDING_FAILED'
   elif not nm:rec['status']='FULL_NAME_NOT_OBSERVED'
   elif len(dates)==0:rec['status']='DOB_NOT_OBSERVED'
   elif len(dates)>1:rec['status']='DOB_SOURCE_AMBIGUOUS'
   else:
    rec['status']='OBSERVATION_DEMOGRAPHICS_VERIFIED';rec['dateOfBirth']=dates[0]
   recs.append(rec)
  except Exception as e:
   fails.append({'globalIndex':r['globalIndex'],'fantacalcioPlayerId':pid,'season':r['season'],'errorType':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc()})
  time.sleep(.16)
 counts=Counter(x['status'] for x in recs);cap=now();status='PASS' if not fails and len(recs)==len(sel) else 'TECHNICAL_FAILURE_NOT_SCIENTIFIC_MISSINGNESS'
 result={'schema':'NEXUS_D1_HISTORICAL_NEVER_RESOLVED_OBSERVATION_DEMOGRAPHICS_SHARD_RESULT_V1','protocolVersion':'1.1','status':status,'capturedAt':cap,'shard':{'start':a.start,'end':a.end,'count':len(sel)},'source':{'subjectCount':445,'observationCount':704,'payloadDecodedSha256':m['payload']['decodedJsonSha256']},'rules':{'providerObservationKey':['Fantacalcio','season','fantacalcioPlayerId'],'providerObservationKeyIsGlobalPersonKey':False,'neutralSeoSlugsUsed':True,'exactSeasonPlayerIdCanonicalBindingRequired':True,'observedNameUsedAsConsistencyEvidenceOnly':True,'observedNameMismatchDoesNotCreatePersonMerge':True,'fullNameRequiredForVerifiedDemographics':True,'singleDayPrecisionDobRequired':True,'personClusteringPerformed':False,'nameSearchUsed':False,'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'computedAgeDerived':False,'f1Started':False,'d2Started':False},'summary':{'observations':len(sel),'recordsCompleted':len(recs),'statusCounts':dict(sorted(counts.items())),'verifiedObservations':counts.get('OBSERVATION_DEMOGRAPHICS_VERIFIED',0),'requestFailures':len(fails)},'requestFailures':fails,'records':recs}
 (out/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 evidence=[]
 for p in sorted(x for x in out.rglob('*') if x.is_file()):
  bb=p.read_bytes();evidence.append({'path':str(p.relative_to(out)),'size':len(bb),'sha256':sha(bb)})
 digest=sha('\n'.join(f"{e['path']}\t{e['size']}\t{e['sha256']}" for e in evidence).encode())
 (out/'MANIFEST.json').write_text(json.dumps({'schema':'NEXUS_D1_HISTORICAL_NEVER_RESOLVED_OBSERVATION_DEMOGRAPHICS_SHARD_MANIFEST_V1','generatedAt':cap,'status':status,'evidenceFileCount':len(evidence),'canonicalEvidenceSha256':digest,'evidence':evidence,'governance':result['rules']},ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result['summary'],indent=2))
 if status!='PASS':raise SystemExit(2)
if __name__=='__main__':main()
