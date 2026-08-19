#!/usr/bin/env python3
"""Acquire Wikidata DOB for the 2,048 historically cross-source-resolved persons.

This is D1 source coverage evidence only. It uses exact full-name/alias mapping;
when exact names collide, historical club context may disambiguate uniquely.
No fuzzy matching, no DOB-based identity selection, no age derivation and no
historical-as-of admission are performed.
"""
from __future__ import annotations

import argparse, base64, hashlib, json, lzma, re, time, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API='https://www.wikidata.org/w/api.php'
UA='FantaNexus-D1-Historical2048/1.0 (+https://github.com/Sidious92/Fantta-Desk-data-Acquisitions)'
Q_HUMAN='Q5'; Q_FOOTBALLER='Q937857'

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b): return hashlib.sha256(b).hexdigest()
def norm(s):
    s=unicodedata.normalize('NFKD',s or '')
    s=''.join(c for c in s if not unicodedata.combining(c)).casefold()
    return re.sub(r'[^a-z0-9]+',' ',s).strip()
def slug(s): return re.sub(r'[^A-Za-z0-9_.-]+','_',s).strip('_')[:150]

def request(params, attempts=6):
    q=urlencode({**params,'format':'json','formatversion':'2','maxlag':'5'})
    req=Request(f'{API}?{q}',headers={'User-Agent':UA,'Accept':'application/json'})
    last='unknown'
    for i in range(attempts):
        try:
            with urlopen(req,timeout=40) as r:
                raw=r.read(); payload=json.loads(raw)
                if payload.get('error'): raise RuntimeError(str(payload['error']))
                time.sleep(0.75)
                return payload,raw
        except HTTPError as e:
            last=f'HTTP {e.code}: {e.reason}'; retry=e.headers.get('Retry-After'); delay=float(retry) if retry and retry.isdigit() else min(20,2*(i+1))
        except URLError as e: last=f'URL error: {e.reason}'; delay=min(20,2*(i+1))
        except Exception as e: last=f'{type(e).__name__}: {e}'; delay=min(20,2*(i+1))
        if i+1<attempts: time.sleep(delay)
    raise RuntimeError(last)

def names(ent):
    out=set()
    for x in (ent.get('labels') or {}).values():
        if isinstance(x,dict) and x.get('value'): out.add(norm(x['value']))
    for xs in (ent.get('aliases') or {}).values():
        for x in xs or []:
            if isinstance(x,dict) and x.get('value'): out.add(norm(x['value']))
    return {x for x in out if x}

def claim_ids(ent,prop):
    out=set()
    for c in (ent.get('claims') or {}).get(prop,[]):
        v=((c.get('mainsnak') or {}).get('datavalue') or {}).get('value')
        if isinstance(v,dict) and v.get('id'): out.add(v['id'])
    return out

def footballer(ent): return Q_HUMAN in claim_ids(ent,'P31') and Q_FOOTBALLER in claim_ids(ent,'P106')
def dob_statements(ent):
    out=[]
    for c in (ent.get('claims') or {}).get('P569',[]):
        v=((c.get('mainsnak') or {}).get('datavalue') or {}).get('value')
        if isinstance(v,dict) and v.get('time'):
            out.append({'statementGuid':c.get('id'),'rank':c.get('rank'),'time':v.get('time'),'precision':v.get('precision'),'calendarmodel':v.get('calendarmodel')})
    return out

def choose_dob(xs):
    if not xs: return 'DOB_MISSING',None
    preferred=[x for x in xs if x.get('rank')=='preferred']; ys=preferred or [x for x in xs if x.get('rank')!='deprecated']
    if len({(x.get('time'),x.get('precision')) for x in ys})!=1: return 'DOB_CONFLICT',None
    return 'DOB_VERIFIED',sorted(ys,key=lambda x:x.get('statementGuid') or '')[0]

def fetch_batches(qids,raw_dir,prefix,props,languages,cache):
    missing=[q for q in qids if q not in cache]
    for i in range(0,len(missing),50):
        batch=missing[i:i+50]
        if not batch: continue
        payload,raw=request({'action':'wbgetentities','ids':'|'.join(batch),'props':props,'languages':languages})
        (raw_dir/f'{prefix}-{i//50:03d}.json').write_bytes(raw)
        for q,e in (payload.get('entities') or {}).items(): cache[q]=e

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--subjects-b64',required=True); ap.add_argument('--manifest',required=True); ap.add_argument('--output',required=True); args=ap.parse_args()
    root=Path(args.output); sd=root/'raw'/'search'; ed=root/'raw'/'entity-batches'; cd=root/'raw'/'club-batches'
    for p in (sd,ed,cd): p.mkdir(parents=True,exist_ok=True)
    m=json.loads(Path(args.manifest).read_text()); xz=base64.b64decode(Path(args.subjects_b64).read_text().strip()); raw=lzma.decompress(xz)
    assert sha(xz)==m['payload']['xzSha256']; assert sha(raw)==m['payload']['decodedJsonSha256']
    doc=json.loads(raw); subjects=doc['subjects']; assert len(subjects)==2048

    searches={}; failures=[]; qids=set()
    for i,s in enumerate(subjects):
        lookup=s['lookupNames'][0]
        try:
            payload,b=request({'action':'wbsearchentities','search':lookup,'language':'en','uselang':'en','type':'item','limit':7})
            p=sd/f'{i:04d}--{slug(s["subjectId"])}--{slug(lookup)}.json'; p.write_bytes(b)
            hits=[h.get('id') for h in payload.get('search') or [] if h.get('id')]; qids.update(hits)
            searches[s['subjectId']]={'lookup':lookup,'hits':hits,'rawPath':str(p.relative_to(root)),'rawSha256':sha(b)}
        except Exception as e:
            searches[s['subjectId']]={'lookup':lookup,'hits':[],'failure':str(e)}; failures.append({'subjectId':s['subjectId'],'stage':'SEARCH','detail':str(e)})

    people={}; fetch_batches(sorted(qids),ed,'people','info|labels|aliases|descriptions|claims','en|it|de|fr|es|pt|pl|hr|sr|bs|sq|tr|nl|el',people)
    club_ids=sorted(set().union(*(claim_ids(e,'P54') for e in people.values() if e)))
    clubs={}; fetch_batches(club_ids,cd,'clubs','info|labels|aliases','en|it|de|fr|es|pt',clubs)

    records=[]
    for s in subjects:
        se=searches[s['subjectId']]; lookup=se['lookup']; exact=[]
        for q in se.get('hits',[]):
            ent=people.get(q) or {}
            if footballer(ent) and norm(lookup) in names(ent): exact.append(q)
        wanted={norm(x) for x in s.get('contextClubs') or []}; context={}; context_matches=[]
        for q in exact:
            tids=sorted(claim_ids(people[q],'P54')); tnames=sorted(set().union(*(names(clubs.get(t) or {}) for t in tids))) if tids else []
            matched=sorted(wanted.intersection(tnames)); context[q]={'teamIds':tids,'teamNamesNormalized':tnames,'matchedContextClubs':matched}
            if matched: context_matches.append(q)
        chosen=None; method=None
        if len(exact)==1: chosen=exact[0]; method='EXACT_FULL_NAME_OR_ALIAS_UNIQUE'
        elif len(exact)>1 and len(context_matches)==1: chosen=context_matches[0]; method='EXACT_FULL_NAME_PLUS_UNIQUE_HISTORICAL_CLUB_CONTEXT'
        base={'subjectId':s['subjectId'],'bridgePersonKey':s.get('bridgePersonKey'),'understatPlayerId':s.get('understatPlayerId'),'lookupName':lookup,'contextClubs':s.get('contextClubs') or [],'seasons':s.get('seasons') or [],'searchEvidence':se,'exactCandidateIds':exact,'contextEvidence':context,'historicalAdmissibility':'NOT_ESTABLISHED_CURRENT_RETRIEVAL_ONLY'}
        if chosen:
            ent=people[chosen]; ds=dob_statements(ent); ds_state,dob=choose_dob(ds)
            records.append({**base,'mappingStatus':'IDENTITY_VERIFIED','mappingMethod':method,'wikidataItemId':chosen,'wikidataLastRevisionId':ent.get('lastrevid'),'wikidataModified':ent.get('modified'),'dateOfBirthStatus':ds_state,'dateOfBirth':dob,'allDobStatements':ds})
        else:
            state='NOT_EVALUATED_TECHNICAL' if se.get('failure') else ('IDENTITY_AMBIGUOUS' if len(exact)>1 else 'IDENTITY_UNRESOLVED')
            records.append({**base,'mappingStatus':state,'mappingMethod':None,'dateOfBirthStatus':'NOT_EVALUATED_TECHNICAL' if state=='NOT_EVALUATED_TECHNICAL' else 'IDENTITY_UNRESOLVED','dateOfBirth':None,'missingReason':'UNKNOWN' if state=='NOT_EVALUATED_TECHNICAL' else 'MAPPING_UNRESOLVED'})

    mc={}; dc={}
    for r in records: mc[r['mappingStatus']]=mc.get(r['mappingStatus'],0)+1; dc[r['dateOfBirthStatus']]=dc.get(r['dateOfBirthStatus'],0)+1
    result={'schema':'NEXUS_D1_HISTORICAL_RESOLVED_PERSON_WIKIDATA_RESULT_V1','protocolVersion':'1.1','status':'PASS' if not failures else 'REVIEW_REQUIRED','declaredUse':'HISTORICAL_POPULATION_COVERAGE_CURRENT_RETRIEVAL_ONLY','capturedAt':now(),'subjectSurface':{'count':2048,'decodedJsonSha256':m['payload']['decodedJsonSha256'],'sourceArtifactId':9162967092},'rules':{'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'computedAgeDerived':False,'currentRetrievalImpliesHistoricalAsOf':False,'trainingPromotionGranted':False,'requestFailureCanBecomeMissingIdentity':False},'summary':{'subjects':2048,'mappingStatus':mc,'dobStatus':dc,'requestFailures':len(failures)},'requestFailures':failures,'records':records}
    (root/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    files=[]
    for p in sorted(x for x in root.rglob('*') if x.is_file() and x.name!='MANIFEST.json'):
        b=p.read_bytes(); files.append({'path':str(p.relative_to(root)),'size':len(b),'sha256':sha(b)})
    digest=hashlib.sha256('\n'.join(f"{x['path']}\t{x['size']}\t{x['sha256']}" for x in files).encode()).hexdigest()
    (root/'MANIFEST.json').write_text(json.dumps({'schema':'NEXUS_D1_HISTORICAL_RESOLVED_PERSON_WIKIDATA_MANIFEST_V1','generatedAt':now(),'files':files,'fileCount':len(files),'canonicalContentSha256':digest},indent=2)+'\n')
    print(json.dumps(result['summary'],indent=2))

if __name__=='__main__': main()
