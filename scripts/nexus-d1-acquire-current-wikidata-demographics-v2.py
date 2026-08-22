#!/usr/bin/env python3
"""Acquire D1 current-505 identity/DOB evidence from Wikidata (v2 subject contract).

Scientific constraints:
- provider IDs are never global person keys;
- no fuzzy matching;
- bridged subjects require exact full-name/alias identity;
- unbridged Fantacalcio short names require deterministic token/initial match
  AND a unique exact Wikidata P54 club-label/alias context match;
- DOB is never used to choose identity;
- request failures never become missing-source evidence;
- no age derivation and no historical-as-of claim;
- subjectId is a technical record key only and, when absent from the minimized
  v2 subject surface, is deterministically materialized as current-fc-<Fantacalcio ID>.
"""
from __future__ import annotations

import argparse, base64, gzip, hashlib, json, re, time, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API='https://www.wikidata.org/w/api.php'
UA='FantaNexus-D1-Current505/2.0 (+https://github.com/Sidious92/Fantta-Desk-data-Acquisitions)'
Q_HUMAN='Q5'; Q_FOOTBALLER='Q937857'

class SourceFailure(RuntimeError): pass

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b): return hashlib.sha256(b).hexdigest()
def norm(s):
    s=unicodedata.normalize('NFKD',s or '')
    s=''.join(c for c in s if not unicodedata.combining(c)).casefold()
    return re.sub(r'[^a-z0-9]+',' ',s).strip()
def compact(s): return re.sub(r'[^a-z0-9]+','',norm(s))
def slug(s): return re.sub(r'[^A-Za-z0-9_.-]+','_',s).strip('_')[:160]

def subject_id(subject):
    source_id=str(subject.get('fantacalcioSourcePlayerId') or '').strip()
    if not source_id:
        raise ValueError('fantacalcioSourcePlayerId missing: cannot materialize deterministic technical subjectId')
    expected=f'current-fc-{source_id}'
    supplied=subject.get('subjectId')
    if supplied is not None and supplied != expected:
        raise ValueError(f'non-canonical subjectId {supplied!r}; expected {expected!r}')
    return expected

def request(params, attempts=6):
    q=urlencode({**params,'format':'json','formatversion':'2','maxlag':'5'})
    req=Request(f'{API}?{q}',headers={'User-Agent':UA,'Accept':'application/json'})
    last='unknown'
    for i in range(attempts):
        try:
            with urlopen(req,timeout=40) as r:
                raw=r.read(); payload=json.loads(raw)
                if payload.get('error'): raise RuntimeError(str(payload['error']))
                time.sleep(0.7)
                return payload,raw
        except HTTPError as e:
            last=f'HTTP {e.code}: {e.reason}'
            retry=e.headers.get('Retry-After'); delay=float(retry) if retry and retry.isdigit() else min(20,2*(i+1))
        except URLError as e: last=f'URL error: {e.reason}'; delay=min(20,2*(i+1))
        except Exception as e: last=f'{type(e).__name__}: {e}'; delay=min(20,2*(i+1))
        if i+1<attempts: time.sleep(delay)
    raise SourceFailure(last)

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

def is_footballer(ent): return Q_HUMAN in claim_ids(ent,'P31') and Q_FOOTBALLER in claim_ids(ent,'P106')
def dob_statements(ent):
    out=[]
    for c in (ent.get('claims') or {}).get('P569',[]):
        v=((c.get('mainsnak') or {}).get('datavalue') or {}).get('value')
        if isinstance(v,dict) and v.get('time'):
            out.append({'statementGuid':c.get('id'),'rank':c.get('rank'),'time':v.get('time'),'precision':v.get('precision'),'calendarmodel':v.get('calendarmodel')})
    return out

def choose_dob(xs):
    if not xs: return 'DOB_MISSING',None
    preferred=[x for x in xs if x.get('rank')=='preferred']
    ys=preferred or [x for x in xs if x.get('rank')!='deprecated']
    if len({(x.get('time'),x.get('precision')) for x in ys})!=1: return 'DOB_CONFLICT',None
    return 'DOB_VERIFIED',sorted(ys,key=lambda x:x.get('statementGuid') or '')[0]

def provider_short_signature(value):
    raw=(value or '').strip(); parts=raw.split(); initial=None
    if parts and parts[-1].endswith('.') and 1 <= len(re.sub(r'[^A-Za-z]','',parts[-1])) <= 4:
        initial=compact(parts.pop())
    base=' '.join(parts) if parts else raw
    base_tokens=[compact(t) for t in norm(base).split() if compact(t)]
    return base_tokens,initial

def short_name_matches(provider_name, entity_names):
    base,initial=provider_short_signature(provider_name)
    if not base: return False
    for n in entity_names:
        toks=[compact(t) for t in n.split() if compact(t)]
        joined=compact(n)
        if not all(any(bt==t or bt==joined for t in toks) for bt in base):
            if not all(bt in joined for bt in base): continue
        if initial:
            others=[t for t in toks if t not in base]
            if not any(t.startswith(initial) for t in others): continue
        return True
    return False

def fetch_entities(qids, raw_dir, prefix, cache):
    missing=[q for q in qids if q not in cache]
    for i in range(0,len(missing),50):
        batch=missing[i:i+50]
        if not batch: continue
        payload,raw=request({'action':'wbgetentities','ids':'|'.join(batch),'props':'info|labels|aliases|descriptions|claims','languages':'en|it|de|fr|es|pt|pl|hr|sr|bs|sq|tr|nl|el'})
        p=raw_dir/f'{prefix}-{i//50:03d}.json'; p.write_bytes(raw)
        for q,e in (payload.get('entities') or {}).items(): cache[q]=e

def fetch_clubs(club_ids, raw_dir, cache):
    missing=[q for q in club_ids if q not in cache]
    for i in range(0,len(missing),50):
        batch=missing[i:i+50]
        payload,raw=request({'action':'wbgetentities','ids':'|'.join(batch),'props':'info|labels|aliases','languages':'en|it|de|fr|es|pt'})
        (raw_dir/f'clubs-{i//50:03d}.json').write_bytes(raw)
        for q,e in (payload.get('entities') or {}).items(): cache[q]=e

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--subjects-b64',required=True); ap.add_argument('--manifest',required=True); ap.add_argument('--output',required=True); args=ap.parse_args()
    root=Path(args.output); search_dir=root/'raw'/'search'; entity_dir=root/'raw'/'entity-batches'; club_dir=root/'raw'/'club-batches'
    for p in (search_dir,entity_dir,club_dir): p.mkdir(parents=True,exist_ok=True)
    manifest=json.loads(Path(args.manifest).read_text())
    encoded=Path(args.subjects_b64).read_text().strip().encode(); gz=base64.b64decode(encoded); raw=gzip.decompress(gz)
    assert sha(gz)==manifest['payload']['gzipSha256']; assert sha(raw)==manifest['payload']['decodedJsonSha256']
    doc=json.loads(raw); subjects=doc['subjects']; assert len(subjects)==505
    technical_ids=[subject_id(s) for s in subjects]
    assert len(set(technical_ids))==505, 'duplicate deterministic technical subjectId'

    searches={}; failures=[]; qids=set()
    for idx,s in enumerate(subjects):
        sid=subject_id(s); lookup=s['lookupNames'][0]
        try:
            payload,b=request({'action':'wbsearchentities','search':lookup,'language':'en','uselang':'en','type':'item','limit':7})
            p=search_dir/f'{idx:03d}--{slug(sid)}--{slug(lookup)}.json'; p.write_bytes(b)
            hits=[h.get('id') for h in payload.get('search') or [] if h.get('id')]
            searches[sid]={'lookup':lookup,'hits':hits,'rawPath':str(p.relative_to(root)),'rawSha256':sha(b)}; qids.update(hits)
        except Exception as e:
            searches[sid]={'lookup':lookup,'hits':[],'failure':str(e)}; failures.append({'subjectId':sid,'stage':'SEARCH','detail':str(e)})

    people={}; fetch_entities(sorted(qids),entity_dir,'people',people)
    club_ids=sorted(set().union(*(claim_ids(e,'P54') for e in people.values() if e)))
    clubs={}; fetch_clubs(club_ids,club_dir,clubs)

    records=[]
    for s in subjects:
        sid=subject_id(s); se=searches[sid]; lookup=se['lookup']; candidates=[]
        for q in se.get('hits',[]):
            ent=people.get(q) or {}
            if not is_footballer(ent): continue
            ens=names(ent)
            full_exact=norm(lookup) in ens
            short_match=short_name_matches(lookup,ens)
            if s.get('bridgePersonKey'):
                if full_exact: candidates.append((q,'EXACT_FULL_NAME_OR_ALIAS'))
            elif full_exact or short_match:
                candidates.append((q,'EXACT_PROVIDER_SHORT_PATTERN' if not full_exact else 'EXACT_NAME_OR_ALIAS'))

        wanted={norm(x) for x in s.get('contextClubs') or []}
        context={}; context_matches=[]
        for q,method in candidates:
            team_ids=sorted(claim_ids(people[q],'P54'))
            team_names=sorted(set().union(*(names(clubs.get(t) or {}) for t in team_ids))) if team_ids else []
            matched=sorted(wanted.intersection(team_names))
            context[q]={'method':method,'teamIds':team_ids,'teamNamesNormalized':team_names,'matchedContextClubs':matched}
            if matched: context_matches.append((q,method))

        chosen=None; method=None
        if s.get('bridgePersonKey'):
            if len(candidates)==1: chosen,method=candidates[0]
            elif len(candidates)>1 and len(context_matches)==1: chosen,method=context_matches[0]; method='EXACT_FULL_NAME_PLUS_UNIQUE_CONTEXT_CLUB'
        else:
            if len(context_matches)==1: chosen,_=context_matches[0]; method='PROVIDER_SHORT_PATTERN_PLUS_UNIQUE_CONTEXT_CLUB'

        base={'subjectId':sid,'fantacalcioSourcePlayerId':s['fantacalcioSourcePlayerId'],'lookupName':lookup,'contextClubs':s['contextClubs'],'classicRole':s['classicRole'],'bridgePersonKey':s.get('bridgePersonKey'),'identityFoundationState':s.get('identityFoundationState'),'identityFoundationMethod':s.get('identityFoundationMethod'),'candidateCount':len(candidates),'contextEvidence':context,'searchEvidence':se,'historicalAdmissibility':'NOT_ESTABLISHED_CURRENT_ACQUISITION'}
        if chosen:
            ent=people[chosen]; ds=dob_statements(ent); dstate,dob=choose_dob(ds)
            records.append({**base,'mappingStatus':'IDENTITY_VERIFIED','mappingMethod':method,'wikidataItemId':chosen,'wikidataLastRevisionId':ent.get('lastrevid'),'wikidataModified':ent.get('modified'),'dateOfBirthStatus':dstate,'dateOfBirth':dob,'allDobStatements':ds})
        else:
            state='IDENTITY_AMBIGUOUS' if len(candidates)>1 else 'IDENTITY_UNRESOLVED'
            if se.get('failure'): state='NOT_EVALUATED_TECHNICAL'
            records.append({**base,'mappingStatus':state,'mappingMethod':None,'wikidataCandidateIds':[q for q,_ in candidates],'dateOfBirthStatus':'NOT_EVALUATED_TECHNICAL' if state=='NOT_EVALUATED_TECHNICAL' else 'IDENTITY_UNRESOLVED','dateOfBirth':None,'missingReason':'UNKNOWN' if state=='NOT_EVALUATED_TECHNICAL' else 'MAPPING_UNRESOLVED'})

    mc={}; dc={}; bridge_mc={}; unbridged_mc={}
    for r in records:
        mc[r['mappingStatus']]=mc.get(r['mappingStatus'],0)+1; dc[r['dateOfBirthStatus']]=dc.get(r['dateOfBirthStatus'],0)+1
        bucket=bridge_mc if r.get('bridgePersonKey') else unbridged_mc; bucket[r['mappingStatus']]=bucket.get(r['mappingStatus'],0)+1
    result={'schema':'NEXUS_D1_CURRENT_2026_27_WIKIDATA_DEMOGRAPHICS_RESULT_V2','protocolVersion':'1.1','status':'PASS' if not failures else 'REVIEW_REQUIRED','declaredUse':'CURRENT_PROBE_POPULATION_COVERAGE','capturedAt':now(),'subjectSurface':{'count':505,'canonicalAsOf':'2026-08-18','schema':manifest['schema'],'decodedJsonSha256':manifest['payload']['decodedJsonSha256']},'rules':{'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'unbridgedRequiresUniqueExactClubContext':True,'computedAgeDerived':False,'currentRetrievalImpliesHistoricalAsOf':False,'trainingPromotionGranted':False,'requestFailureCanBecomeMissingIdentity':False,'technicalSubjectIdDerivedFromProviderObservationId':True},'summary':{'subjects':505,'mappingStatus':mc,'dobStatus':dc,'bridgedMappingStatus':bridge_mc,'unbridgedMappingStatus':unbridged_mc,'requestFailures':len(failures)},'requestFailures':failures,'records':records}
    (root/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    files=[]
    for p in sorted(x for x in root.rglob('*') if x.is_file() and x.name!='MANIFEST.json'):
        b=p.read_bytes(); files.append({'path':str(p.relative_to(root)),'size':len(b),'sha256':sha(b)})
    digest=hashlib.sha256('\n'.join(f"{x['path']}\t{x['size']}\t{x['sha256']}" for x in files).encode()).hexdigest()
    (root/'MANIFEST.json').write_text(json.dumps({'schema':'NEXUS_D1_CURRENT_2026_27_WIKIDATA_MANIFEST_V2','generatedAt':now(),'files':files,'fileCount':len(files),'canonicalContentSha256':digest},indent=2)+'\n')
    print(json.dumps(result['summary'],indent=2))

if __name__=='__main__': main()
