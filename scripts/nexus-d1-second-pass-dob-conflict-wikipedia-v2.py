#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, html, json, re, time, traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

UA='FantaNexus-D1/1.1 (private scientific identity-demographics audit)'
RETRYABLE={429,500,502,503,504}
MONTHS={
 'january':1,'february':2,'march':3,'april':4,'may':5,'june':6,'july':7,'august':8,'september':9,'october':10,'november':11,'december':12,
 'gennaio':1,'febbraio':2,'marzo':3,'aprile':4,'maggio':5,'giugno':6,'luglio':7,'agosto':8,'settembre':9,'ottobre':10,'novembre':11,'dicembre':12,
}

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha256(b:bytes): return hashlib.sha256(b).hexdigest()
def norm_space(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s))).strip()

def fetch(url, attempts=8):
    last=None
    for i in range(attempts):
        try:
            req=Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/json;q=0.9,*/*;q=0.8'})
            with urlopen(req,timeout=45) as r: return r.status,dict(r.headers.items()),r.read(),r.geturl()
        except HTTPError as e:
            last=e
            if e.code not in RETRYABLE: raise
        except (URLError,TimeoutError) as e: last=e
        time.sleep(min(30,1.5*(2**i)))
    raise last

def exact_dates(stmts):
    out=set()
    for s in stmts or []:
        t=s.get('time'); p=s.get('precision')
        if isinstance(t,str) and p==11:
            m=re.match(r'^\+(\d{4}-\d{2}-\d{2})T',t)
            if m: out.add(m.group(1))
    return sorted(out)

def parse_human_date(s):
    s=norm_space(s).lower().replace(',',' ')
    m=re.search(r'\b(\d{1,2})\s+([a-zà-ÿ]+)\s+(\d{4})\b',s,re.I)
    if not m: return None
    d=int(m.group(1)); mon=MONTHS.get(m.group(2)); y=int(m.group(3))
    if not mon: return None
    try: return f'{y:04d}-{mon:02d}-{d:02d}'
    except Exception: return None

def bday_candidates(text):
    vals=set(); evidence=[]
    # Any element whose class contains bday; parse datetime/content independent of attribute order.
    for m in re.finditer(r'<(?P<tag>[a-z0-9]+)(?P<attrs>[^>]*\bclass=["\'][^"\']*\bbday\b[^"\']*["\'][^>]*)>(?P<body>.*?)</(?P=tag)>',text,re.I|re.S):
        attrs=m.group('attrs'); body=m.group('body')
        dm=re.search(r'\bdatetime=["\'](\d{4}-\d{2}-\d{2})(?:T[^"\']*)?["\']',attrs,re.I)
        d=dm.group(1) if dm else None
        if not d:
            iso=re.search(r'\b(\d{4}-\d{2}-\d{2})\b',norm_space(body))
            d=iso.group(1) if iso else parse_human_date(body)
        evidence.append({'kind':'CLASS_BDAY','text':norm_space(body)[:200],'date':d})
        if d: vals.add(d)
    # Time elements with birth/bday class in any attribute ordering.
    for m in re.finditer(r'<time(?P<attrs>[^>]*)>(?P<body>.*?)</time>',text,re.I|re.S):
        attrs=m.group('attrs')
        if not re.search(r'class=["\'][^"\']*(?:bday|birth)[^"\']*["\']',attrs,re.I): continue
        dm=re.search(r'datetime=["\'](\d{4}-\d{2}-\d{2})(?:T[^"\']*)?["\']',attrs,re.I)
        d=dm.group(1) if dm else parse_human_date(m.group('body'))
        evidence.append({'kind':'TIME_BIRTH','text':norm_space(m.group('body'))[:200],'date':d})
        if d: vals.add(d)
    return sorted(vals),evidence

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--subjects',required=True); ap.add_argument('--output',required=True); a=ap.parse_args()
    sp=Path(a.subjects); sb=sp.read_bytes(); src=json.loads(sb)
    if src.get('status')!='PASS': raise RuntimeError('SECOND_PASS_SURFACE_NOT_PASS')
    selected=[]
    for key in ('currentOpen','historicalOpen'):
        for r in src.get(key) or []:
            if r.get('mappingStatus')=='IDENTITY_VERIFIED' and r.get('dateOfBirthStatus')=='DOB_CONFLICT': selected.append(r)
    if len(selected)!=47: raise RuntimeError(f'EXPECTED_47_GOT_{len(selected)}')
    by={}
    for r in selected:
        q=r.get('wikidataItemId')
        if not q: raise RuntimeError('VERIFIED_CONFLICT_WITHOUT_QID')
        x=by.setdefault(q,{'qid':q,'sourceRecords':[],'conflictDates':set()})
        x['sourceRecords'].append({'scope':r.get('scope'),'subjectId':r.get('subjectId'),'firstPassSubjectLocator':r.get('firstPassSubjectLocator'),'lookupName':r.get('lookupName'),'bridgePersonKey':r.get('bridgePersonKey')})
        x['conflictDates'].update(exact_dates(r.get('allDobStatements')))
    if len(by)!=46: raise RuntimeError(f'EXPECTED_46_QIDS_GOT_{len(by)}')
    out=Path(a.output); raw=out/'raw'; raw.mkdir(parents=True,exist_ok=True)
    recs=[]; fails=[]
    for i,q in enumerate(sorted(by)):
        base=by[q]; rec={'wikidataItemId':q,'sourceRecords':base['sourceRecords'],'conflictDates':sorted(base['conflictDates']),'identityBindingMethod':'EXACT_VERIFIED_WIKIDATA_QID_TO_EXACT_WIKIPEDIA_SITELINK','dobUsedForIdentitySelection':False}
        try:
            u=f'https://www.wikidata.org/wiki/Special:EntityData/{q}.json'; st,h,b,fu=fetch(u); ep=raw/f'{i:03d}--{q}--wikidata.json'; ep.write_bytes(b)
            e=json.loads(b)['entities'][q]; sl=e.get('sitelinks') or {}; site='itwiki' if 'itwiki' in sl else ('enwiki' if 'enwiki' in sl else None)
            rec['routingEvidence']={'sitelinkSite':site,'rawPath':str(ep.relative_to(out)),'rawSha256':sha256(b)}
            if not site:
                rec['status']='SOURCE_NO_COVERAGE'; recs.append(rec); continue
            title=sl[site]['title']; lang='it' if site=='itwiki' else 'en'; pu=f'https://{lang}.wikipedia.org/wiki/{quote(title.replace(" ","_"),safe="()_,-%")}'
            st2,h2,p,fp=fetch(pu); pp=raw/f'{i:03d}--{q}--{lang}wiki.html'; pp.write_bytes(p); text=p.decode('utf-8',errors='replace')
            dates,ev=bday_candidates(text)
            rec['wikipediaEvidence']={'site':site,'title':title,'requestedUrl':pu,'finalUrl':fp,'httpStatus':st2,'rawPath':str(pp.relative_to(out)),'rawBytes':len(p),'rawSha256':sha256(p),'bdayCandidates':dates,'bdayEvidence':ev}
            matching=sorted(set(dates)&set(rec['conflictDates']))
            rec['matchingConflictDates']=matching
            if len(matching)==1:
                rec['status']='DOB_CORROBORATED_BY_WIKIPEDIA'; rec['corroboratedDate']=matching[0]
            elif len(matching)>1: rec['status']='DOB_SOURCE_AMBIGUOUS'
            elif dates: rec['status']='DOB_NEW_CONFLICT'
            else: rec['status']='DOB_NOT_OBSERVED'
            recs.append(rec)
        except Exception as exc:
            fails.append({'wikidataItemId':q,'errorType':type(exc).__name__,'detail':str(exc),'traceback':traceback.format_exc()})
        time.sleep(.12)
    counts=Counter(r['status'] for r in recs); cap=now(); status='PASS' if not fails and len(recs)==46 else 'TECHNICAL_FAILURE_NOT_SCIENTIFIC_MISSINGNESS'
    result={'schema':'NEXUS_D1_SECOND_PASS_DOB_CONFLICT_WIKIPEDIA_RESULT_V2','protocolVersion':'1.1','status':status,'capturedAt':cap,'sourceSurface':{'path':str(sp),'bytes':len(sb),'sha256':sha256(sb),'rawConflictRecords':47,'uniqueVerifiedWikidataPersons':46},'rules':{'identityBindingExactVerifiedWikidataQid':True,'wikipediaPageSelectedOnlyByExactQidSitelink':True,'nameSearchUsed':False,'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'computedAgeDerived':False,'dobInferred':False,'onlyExistingConflictDateMayResolve':True,'currentRetrievalImpliesHistoricalAsOf':False,'trainingPromotionGranted':False,'f1Started':False,'d2Started':False},'summary':{'rawConflictRecords':47,'uniquePersons':46,'recordsCompleted':len(recs),'statusCounts':dict(sorted(counts.items())),'corroboratedPersons':counts.get('DOB_CORROBORATED_BY_WIKIPEDIA',0),'requestFailures':len(fails)},'requestFailures':fails,'records':recs}
    (out/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    evidence=[]
    for p in sorted(x for x in out.rglob('*') if x.is_file()):
        bb=p.read_bytes(); evidence.append({'path':str(p.relative_to(out)),'size':len(bb),'sha256':sha256(bb)})
    digest=sha256('\n'.join(f"{x['path']}\t{x['size']}\t{x['sha256']}" for x in evidence).encode())
    (out/'MANIFEST.json').write_text(json.dumps({'schema':'NEXUS_D1_SECOND_PASS_DOB_CONFLICT_WIKIPEDIA_MANIFEST_V2','generatedAt':cap,'status':status,'evidenceFileCount':len(evidence),'canonicalEvidenceSha256':digest,'evidence':evidence,'governance':result['rules']},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['summary'],indent=2))
    if status!='PASS': raise SystemExit(2)
if __name__=='__main__': main()
