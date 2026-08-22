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
def slug(s):
 s=html.unescape(str(s));s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower();return re.sub(r'[^a-z0-9]+','-',s).strip('-') or 'x'
def norm_tokens(s):
 s=html.unescape(str(s));s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower();return tuple(sorted(x for x in re.split(r'[^a-z0-9]+',s) if x))
def clean(s):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def fetch(u,attempts=7):
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
  time.sleep(min(20,1.3*(2**i)))
 raise last
def parse_h1(t):
 m=re.search(r'<h1[^>]*>(.*?)</h1>',t,re.I|re.S);return clean(m.group(1)) if m else None
def canonical(t):
 for p in [r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']']:
  m=re.search(p,t,re.I)
  if m:return html.unescape(m.group(1))
def parse_dob(t):
 vals=set();plain=clean(t)
 for d,m,y in re.findall(r'\bNato\s+il\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]{3,10})\s+(\d{4})\b',plain,re.I):
  k=unicodedata.normalize('NFKD',m).encode('ascii','ignore').decode().lower()[:3]
  if k in MONTHS:vals.add(f'{int(y):04d}-{MONTHS[k]:02d}-{int(d):02d}')
 return sorted(vals)
def season_slug(s):return str(s).replace('/','-')
def reconstruct_subjects(manifest_path):
 m=json.loads(Path(manifest_path).read_text());parts=[]
 for c in m['payload']['chunks']:
  t=Path(c['path']).read_text().strip();assert len(t)==c['chars'];assert hashlib.sha256(t.encode()).hexdigest()==c['textSha256'];parts.append(t)
 raw=lzma.decompress(base64.b64decode(''.join(parts),validate=True));assert hashlib.sha256(raw).hexdigest()==m['payload']['decodedJsonSha256'];return json.loads(raw),m

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--subjects-manifest',required=True);ap.add_argument('--second-pass',required=True);ap.add_argument('--contract',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
 contract=json.loads(Path(a.contract).read_text());assert contract['status']=='PASS';assert contract['contract']['providerObservationKeyIsGlobalPersonKey'] is False
 surf,sm=reconstruct_subjects(a.subjects_manifest);by={str(s['understatPlayerId']):s for s in surf['subjects']}
 spb=Path(a.second_pass).read_bytes();sp=json.loads(spb);assert sp['status']=='PASS'
 rows=[r for r in sp['historicalOpen'] if r.get('mappingStatus')!='IDENTITY_VERIFIED'];assert len(rows)==109
 out=Path(a.output);raw=out/'raw';raw.mkdir(parents=True,exist_ok=True)
 recs=[];tech=[];candidate_requests=0
 for idx,r in enumerate(rows):
  b=r.get('bridgePersonKey') or '';uid=b.split(':',1)[1] if b.startswith('understat:') else str(r.get('understatPlayerId') or '')
  s=by.get(uid)
  if not s:raise RuntimeError(f'OPEN_UNDERSTAT_NOT_IN_SUBJECT_SURFACE:{uid}')
  ids=[str(x) for x in s.get('fantacalcioObservationIds') or []];seasons=[str(x) for x in s.get('seasons') or []];lookups=[html.unescape(str(x)) for x in s.get('lookupNames') or []];clubs=[str(x) for x in s.get('contextClubs') or []]
  if not ids or not seasons or not lookups:raise RuntimeError(f'MISSING_HISTORICAL_OBSERVATION_ROUTE:{uid}')
  lookup_token_sets={norm_tokens(x) for x in lookups};accepted=[];attempts=[]
  for pid in ids:
   for season in seasons:
    candidate_requests+=1
    u=f'https://www.fantacalcio.it/serie-a/squadre/{slug(clubs[0] if clubs else "x")}/{slug(lookups[0])}/{pid}/{season_slug(season)}'
    ar={'fantacalcioPlayerId':pid,'season':season,'requestedUrl':u}
    try:
     st,h,body,fu=fetch(u)
     ar['httpStatus']=st
     if st==404:
      ar['status']='NO_PAGE_FOR_CANDIDATE';attempts.append(ar);continue
     p=raw/f'{idx:03d}--u{uid}--fc{pid}--{season_slug(season)}.html';p.write_bytes(body);t=body.decode('utf-8',errors='replace');can=canonical(t);nm=parse_h1(t);dates=parse_dob(t)
     bind=('/'+pid+'/') in ((can or fu)+'/') and season_slug(season) in (can or fu)
     nameok=bool(nm) and norm_tokens(nm) in lookup_token_sets
     ar.update({'finalUrl':fu,'canonicalUrl':can,'exactSeasonPlayerIdBound':bind,'fullName':nm,'exactNormalizedNameTokenSetMatch':nameok,'dobCandidates':dates,'rawPath':str(p.relative_to(out)),'rawBytes':len(body),'rawSha256':sha(body)})
     if bind and nameok and len(dates)==1:
      ar['status']='ACCEPTED_EXACT_OBSERVATION';ar['dateOfBirth']=dates[0];accepted.append(ar)
     elif not bind:ar['status']='OBSERVATION_BINDING_FAILED'
     elif not nameok:ar['status']='NAME_TOKEN_SET_MISMATCH'
     elif len(dates)==0:ar['status']='DOB_NOT_OBSERVED'
     else:ar['status']='DOB_SOURCE_AMBIGUOUS'
     attempts.append(ar)
    except Exception as e:
     tech.append({'understatPlayerId':uid,'fantacalcioPlayerId':pid,'season':season,'errorType':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc()})
    time.sleep(.12)
  dobs=sorted({x['dateOfBirth'] for x in accepted})
  if len(dobs)==1:status='HISTORICAL_PERSON_DOB_VERIFIED_BY_EXACT_FC_OBSERVATION'
  elif len(dobs)>1:status='DOB_CONFLICT_ACROSS_EXACT_FC_OBSERVATIONS'
  else:status='DOB_UNRESOLVED_NO_ACCEPTED_EXACT_FC_OBSERVATION'
  recs.append({'subjectId':s['subjectId'],'bridgePersonKey':s['bridgePersonKey'],'understatPlayerId':uid,'lookupNames':lookups,'contextClubs':clubs,'fantacalcioObservationIds':ids,'seasons':seasons,'status':status,'dateOfBirth':dobs[0] if len(dobs)==1 else None,'distinctAcceptedDobValues':dobs,'acceptedObservationCount':len(accepted),'attempts':attempts})
 counts=Counter(r['status'] for r in recs);cap=now();overall='PASS' if not tech and len(recs)==109 else 'TECHNICAL_FAILURE_NOT_SCIENTIFIC_MISSINGNESS'
 result={'schema':'NEXUS_D1_HISTORICAL_OPEN_FANTACALCIO_DEMOGRAPHICS_RESULT_V1','protocolVersion':'1.1','status':overall,'capturedAt':cap,'source':{'secondPassPath':a.second_pass,'secondPassBytes':len(spb),'secondPassSha256':sha(spb),'historicalSubjectDecodedSha256':sm['payload']['decodedJsonSha256']},'rules':{'personBridgeAuthority':'D0_DERIVED_UNDERSTAT_BACKED_PERSON_SURFACE','providerObservationKey':['Fantacalcio','season','fantacalcioPlayerId'],'providerIdUsedAsGlobalHistoricalPersonKey':False,'exactSeasonPlayerIdCanonicalBindingRequired':True,'exactNormalizedNameTokenSetRequired':True,'nameSearchUsed':False,'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'computedAgeDerived':False,'currentRetrievalImpliesHistoricalAsOf':False,'trainingPromotionGranted':False,'f1Started':False,'d2Started':False},'summary':{'subjects':109,'candidateRequests':candidate_requests,'recordsCompleted':len(recs),'statusCounts':dict(sorted(counts.items())),'dobVerifiedSubjects':counts.get('HISTORICAL_PERSON_DOB_VERIFIED_BY_EXACT_FC_OBSERVATION',0),'requestFailures':len(tech)},'requestFailures':tech,'records':recs}
 (out/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 evidence=[]
 for p in sorted(x for x in out.rglob('*') if x.is_file()):
  bb=p.read_bytes();evidence.append({'path':str(p.relative_to(out)),'size':len(bb),'sha256':sha(bb)})
 digest=sha('\n'.join(f"{e['path']}\t{e['size']}\t{e['sha256']}" for e in evidence).encode())
 (out/'MANIFEST.json').write_text(json.dumps({'schema':'NEXUS_D1_HISTORICAL_OPEN_FANTACALCIO_DEMOGRAPHICS_MANIFEST_V1','generatedAt':cap,'status':overall,'evidenceFileCount':len(evidence),'canonicalEvidenceSha256':digest,'evidence':evidence,'governance':result['rules']},ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result['summary'],indent=2))
 if overall!='PASS':raise SystemExit(2)
if __name__=='__main__':main()
