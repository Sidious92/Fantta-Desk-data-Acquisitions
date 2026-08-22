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
def toks(s):
 s=html.unescape(str(s));s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower();return set(x for x in re.split(r'[^a-z0-9]+',s) if x)
def fetch(u,attempts=8):
 last=None
 for i in range(attempts):
  try:
   req=Request(u,headers={'User-Agent':UA,'Accept':'text/html,*/*;q=0.8','Accept-Language':'it-IT,it;q=0.9'})
   with urlopen(req,timeout=45) as r:return r.status,dict(r.headers.items()),r.read(),r.geturl()
  except HTTPError as e:
   if e.code==404:return 404,{},e.read(),u
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
def conflict_dates(r):
 vals=set()
 for s in r.get('allDobStatements') or []:
  if s.get('precision')==11 and isinstance(s.get('time'),str):
   m=re.match(r'^\+(\d{4}-\d{2}-\d{2})T',s['time'])
   if m:vals.add(m.group(1))
 return sorted(vals)
def reconstruct(manifest):
 m=json.loads(Path(manifest).read_text());parts=[]
 for c in m['payload']['chunks']:
  t=Path(c['path']).read_text().strip();assert len(t)==c['chars'];assert sha(t.encode())==c['textSha256'];parts.append(t)
 raw=lzma.decompress(base64.b64decode(''.join(parts),validate=True));assert sha(raw)==m['payload']['decodedJsonSha256'];return json.loads(raw)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--subjects-manifest',required=True);ap.add_argument('--second-pass',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
 surf=reconstruct(a.subjects_manifest);by={str(s['understatPlayerId']):s for s in surf['subjects']};sp=json.loads(Path(a.second_pass).read_text())
 rows=[r for r in sp['historicalOpen'] if r.get('mappingStatus')=='IDENTITY_VERIFIED' and r.get('dateOfBirthStatus')=='DOB_CONFLICT'];assert len(rows)==46
 out=Path(a.output);raw=out/'raw';raw.mkdir(parents=True,exist_ok=True);recs=[];fails=[];requests=0
 for idx,r in enumerate(rows):
  b=r.get('bridgePersonKey') or '';uid=b.split(':',1)[1] if b.startswith('understat:') else str(r.get('understatPlayerId') or '')
  s=by.get(uid)
  if not s:raise RuntimeError(f'CONFLICT_UNDERSTAT_NOT_IN_SURFACE:{uid}')
  ids=[str(x) for x in s.get('fantacalcioObservationIds') or []];seasons=[str(x) for x in s.get('seasons') or []];lookups=[html.unescape(str(x)) for x in s.get('lookupNames') or []];lookupsets=[toks(x) for x in lookups if toks(x)];existing=conflict_dates(r)
  if len(existing)<2:raise RuntimeError(f'CONFLICT_WITH_LT2_DAY_DATES:{uid}')
  accepted=[];attempts=[]
  for pid in ids:
   for season in seasons:
    requests+=1;ss=season.replace('/','-');u=f'https://www.fantacalcio.it/serie-a/squadre/x/x/{pid}/{ss}';ar={'fantacalcioPlayerId':pid,'season':season,'requestedUrl':u}
    try:
     st,h,body,fu=fetch(u);ar['httpStatus']=st
     if st==404:ar['status']='NO_PAGE_FOR_CANDIDATE';attempts.append(ar);continue
     p=raw/f'{idx:03d}--u{uid}--fc{pid}--{ss}.html';p.write_bytes(body);text=body.decode('utf-8',errors='replace');can=canonical(text);nm=h1(text);dates=dob(text);bind=('/'+pid+'/') in ((can or fu)+'/') and ss in (can or fu);full=toks(nm or '');nameok=bool(full) and any(ls.issubset(full) for ls in lookupsets)
     ar.update({'finalUrl':fu,'canonicalUrl':can,'exactSeasonPlayerIdBound':bind,'fullName':nm,'lookupNameTokenSubsetOfFullName':nameok,'dobCandidates':dates,'rawPath':str(p.relative_to(out)),'rawSha256':sha(body),'rawBytes':len(body)})
     if bind and nameok and len(dates)==1:
      ar['status']='ACCEPTED_EXACT_OBSERVATION';ar['dateOfBirth']=dates[0];accepted.append(ar)
     elif not bind:ar['status']='OBSERVATION_BINDING_FAILED'
     elif not nameok:ar['status']='NAME_CONSISTENCY_FAILED'
     elif not dates:ar['status']='DOB_NOT_OBSERVED'
     else:ar['status']='DOB_SOURCE_AMBIGUOUS'
     attempts.append(ar)
    except Exception as e:fails.append({'understatPlayerId':uid,'fantacalcioPlayerId':pid,'season':season,'errorType':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc()})
    time.sleep(.12)
  vals=sorted({x['dateOfBirth'] for x in accepted});matching=sorted(set(vals)&set(existing))
  if len(matching)==1 and len(vals)==1:st='DOB_CONFLICT_RESOLVED_BY_EXACT_FC_OBSERVATION';resolved=matching[0]
  elif len(matching)==1 and all(v==matching[0] for v in vals):st='DOB_CONFLICT_RESOLVED_BY_EXACT_FC_OBSERVATION';resolved=matching[0]
  elif not vals:st='DOB_CONFLICT_UNRESOLVED_NO_ACCEPTED_FC_OBSERVATION';resolved=None
  elif not matching:st='DOB_NEW_CONFLICT_FROM_FC';resolved=None
  else:st='DOB_CONFLICT_REMAINS_MULTIPLE_SUPPORTED';resolved=None
  recs.append({'subjectId':r['subjectId'],'bridgePersonKey':r.get('bridgePersonKey'),'understatPlayerId':uid,'wikidataItemId':r.get('wikidataItemId'),'lookupNames':lookups,'existingConflictDates':existing,'acceptedFantacalcioDobValues':vals,'matchingExistingConflictDates':matching,'status':st,'dateOfBirth':resolved,'acceptedObservationCount':len(accepted),'attempts':attempts})
 c=Counter(x['status'] for x in recs);cap=now();overall='PASS' if not fails and len(recs)==46 else 'TECHNICAL_FAILURE_NOT_SCIENTIFIC_MISSINGNESS'
 result={'schema':'NEXUS_D1_HISTORICAL_DOB_CONFLICT_FANTACALCIO_RESULT_V1','protocolVersion':'1.1','status':overall,'capturedAt':cap,'rules':{'identityAuthority':'VERIFIED_WIKIDATA_QID_PLUS_D0_UNDERSTAT_PERSON_BRIDGE','providerObservationKey':['Fantacalcio','season','fantacalcioPlayerId'],'providerIdUsedAsGlobalHistoricalPersonKey':False,'exactSeasonPlayerIdBindingRequired':True,'lookupNameTokenSubsetConsistencyRequired':True,'onlyExistingWikidataConflictDateMayResolve':True,'nameSearchUsed':False,'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'computedAgeDerived':False,'historicalAsOfGranted':False,'f1Started':False,'d2Started':False},'summary':{'subjects':46,'candidateRequests':requests,'recordsCompleted':len(recs),'statusCounts':dict(sorted(c.items())),'resolvedConflicts':c.get('DOB_CONFLICT_RESOLVED_BY_EXACT_FC_OBSERVATION',0),'requestFailures':len(fails)},'requestFailures':fails,'records':recs}
 (out/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');e=[]
 for p in sorted(x for x in out.rglob('*') if x.is_file()):
  bb=p.read_bytes();e.append({'path':str(p.relative_to(out)),'size':len(bb),'sha256':sha(bb)})
 digest=sha('\n'.join(f"{x['path']}\t{x['size']}\t{x['sha256']}" for x in e).encode());(out/'MANIFEST.json').write_text(json.dumps({'schema':'NEXUS_D1_HISTORICAL_DOB_CONFLICT_FANTACALCIO_MANIFEST_V1','generatedAt':cap,'status':overall,'evidenceFileCount':len(e),'canonicalEvidenceSha256':digest,'evidence':e,'governance':result['rules']},ensure_ascii=False,indent=2)+'\n');print(json.dumps(result['summary'],indent=2))
 if overall!='PASS':raise SystemExit(2)
if __name__=='__main__':main()
