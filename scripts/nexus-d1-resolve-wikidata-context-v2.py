#!/usr/bin/env python3
"""Resolve D1 Wikidata v1 ambiguities using exact club-context evidence only.

Input is the frozen/persisted v1 probe RESULT. This stage never fuzzy-matches,
never derives age, never uses DOB to choose identity, and never promotes training.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "FantaNexus-D1-Demographics-Context/2.0 (+https://github.com/Sidious92/Fantta-Desk-data-Acquisitions)"


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')


def norm(value):
    value = unicodedata.normalize('NFKD', value or '')
    value = ''.join(c for c in value if not unicodedata.combining(c)).casefold()
    return re.sub(r'[^a-z0-9]+',' ',value).strip()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def request_json(params, attempts=5):
    query=urlencode({**params,'format':'json','formatversion':'2','maxlag':'5'})
    req=Request(f'{API}?{query}',headers={'User-Agent':USER_AGENT,'Accept':'application/json'})
    last='unknown'
    for attempt in range(attempts):
        try:
            with urlopen(req,timeout=35) as r:
                raw=r.read()
                payload=json.loads(raw)
                if payload.get('error'):
                    raise RuntimeError(str(payload['error']))
                time.sleep(1.0)
                return payload,raw
        except HTTPError as exc:
            last=f'HTTP {exc.code}: {exc.reason}'
            retry=exc.headers.get('Retry-After')
            delay=float(retry) if retry and retry.isdigit() else min(15.0,2.0*(attempt+1))
        except URLError as exc:
            last=f'URL error: {exc.reason}'; delay=min(15.0,2.0*(attempt+1))
        except Exception as exc:
            last=f'{type(exc).__name__}: {exc}'; delay=min(15.0,2.0*(attempt+1))
        if attempt+1<attempts: time.sleep(delay)
    raise RuntimeError(f'Wikidata request failed after {attempts} attempts: {last}')


def claim_ids(entity, prop):
    out=set()
    for claim in (entity.get('claims') or {}).get(prop,[]):
        value=((claim.get('mainsnak') or {}).get('datavalue') or {}).get('value')
        if isinstance(value,dict) and value.get('id'): out.add(value['id'])
    return out


def names(entity):
    out=set()
    for item in (entity.get('labels') or {}).values():
        if isinstance(item,dict) and item.get('value'): out.add(norm(item['value']))
    for items in (entity.get('aliases') or {}).values():
        for item in items or []:
            if isinstance(item,dict) and item.get('value'): out.add(norm(item['value']))
    return {x for x in out if x}


def dob_statements(entity):
    out=[]
    for claim in (entity.get('claims') or {}).get('P569',[]):
        value=((claim.get('mainsnak') or {}).get('datavalue') or {}).get('value')
        if isinstance(value,dict) and value.get('time'):
            out.append({'statementGuid':claim.get('id'),'rank':claim.get('rank'),'time':value.get('time'),'precision':value.get('precision'),'calendarmodel':value.get('calendarmodel')})
    return out


def choose_dob(statements):
    if not statements: return 'DOB_MISSING',None
    preferred=[x for x in statements if x.get('rank')=='preferred']
    candidates=preferred or [x for x in statements if x.get('rank')!='deprecated']
    distinct={(x.get('time'),x.get('precision')) for x in candidates}
    if len(distinct)!=1: return 'DOB_CONFLICT',None
    return 'DOB_VERIFIED',sorted(candidates,key=lambda x:x.get('statementGuid') or '')[0]


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--input',required=True)
    ap.add_argument('--output',required=True)
    args=ap.parse_args()
    source_path=Path(args.input)
    source_bytes=source_path.read_bytes()
    source=json.loads(source_bytes)
    if source.get('status') not in {'PASS','REVIEW_REQUIRED'}:
        raise RuntimeError('v2 context resolver requires a completed scientific v1 probe')

    root=Path(args.output); raw=root/'raw'; raw.mkdir(parents=True,exist_ok=True)
    records=[]; failures=[]
    for record in source['records']:
        rec=json.loads(json.dumps(record))
        if rec.get('mappingStatus')!='IDENTITY_AMBIGUOUS':
            rec['v2Resolution']='UNCHANGED_FROM_V1'
            records.append(rec); continue

        candidate_ids=rec.get('wikidataCandidateIds') or []
        try:
            people_payload,people_raw=request_json({'action':'wbgetentities','ids':'|'.join(candidate_ids),'props':'info|labels|aliases|descriptions|claims','languages':'en|it|pt|es'})
            ppath=raw/f"{rec['subjectId']}--candidate-people.json"; ppath.write_bytes(people_raw)
            people=people_payload.get('entities') or {}
            club_ids=sorted(set().union(*(claim_ids(people.get(qid) or {},'P54') for qid in candidate_ids)))
            clubs={}
            club_path=None
            if club_ids:
                club_payload,club_raw=request_json({'action':'wbgetentities','ids':'|'.join(club_ids),'props':'info|labels|aliases','languages':'en|it|pt|es'})
                club_path=raw/f"{rec['subjectId']}--candidate-clubs.json"; club_path.write_bytes(club_raw)
                clubs=club_payload.get('entities') or {}
        except Exception as exc:
            rec['v2Resolution']='REQUEST_FAILED'
            rec['v2RequestFailure']=str(exc)
            failures.append(rec['subjectId'])
            records.append(rec); continue

        wanted={norm(x) for x in rec.get('contextClubs') or [] if norm(x)}
        matches=[]; context_evidence={}
        for qid in candidate_ids:
            team_ids=sorted(claim_ids(people.get(qid) or {},'P54'))
            team_names=sorted(set().union(*(names(clubs.get(team_id) or {}) for team_id in team_ids))) if team_ids else []
            matched=sorted(wanted.intersection(team_names))
            context_evidence[qid]={'teamIds':team_ids,'teamNamesNormalized':team_names,'matchedContextClubs':matched}
            if matched: matches.append(qid)

        rec['v2ContextEvidence']={
            'subjectContextClubs':rec.get('contextClubs') or [],
            'candidateEvidence':context_evidence,
            'candidatePeopleRaw':str(ppath.relative_to(root)),
            'candidatePeopleRawSha256':sha(people_raw),
            'candidateClubsRaw':str(club_path.relative_to(root)) if club_path else None,
            'candidateClubsRawSha256':sha(club_raw) if club_path else None,
        }
        if len(matches)==1:
            qid=matches[0]; ent=people[qid]; statements=dob_statements(ent); dob_state,dob=choose_dob(statements)
            rec['v1AmbiguousCandidateIds']=candidate_ids
            rec['v2Resolution']='RESOLVED_EXACT_CONTEXT_CLUB_UNIQUE'
            rec['mappingStatus']='IDENTITY_VERIFIED'
            rec['mappingMethod']='EXACT_NAME_PLUS_UNIQUE_CONTEXT_CLUB'
            rec['wikidataItemId']=qid
            rec['wikidataLastRevisionId']=ent.get('lastrevid')
            rec['wikidataModified']=ent.get('modified')
            rec['dateOfBirthStatus']=dob_state
            rec['dateOfBirth']=dob
            rec['allDobStatements']=statements
            rec.pop('wikidataCandidateIds',None); rec.pop('missingReason',None)
        else:
            rec['v2Resolution']='AMBIGUITY_REMAINS'
        records.append(rec)

    mapping={}; dob={}
    for r in records:
        mapping[r.get('mappingStatus') or 'NOT_EVALUATED']=mapping.get(r.get('mappingStatus') or 'NOT_EVALUATED',0)+1
        dob[r.get('dateOfBirthStatus') or 'UNKNOWN']=dob.get(r.get('dateOfBirthStatus') or 'UNKNOWN',0)+1
    collision=[r for r in records if r['subjectId'].startswith('historical-fc-65-')]
    collision_ids=[r.get('wikidataItemId') for r in collision if r.get('mappingStatus')=='IDENTITY_VERIFIED']
    collision_pass=len(collision_ids)==2 and len(set(collision_ids))==2
    status='PASS' if not failures and mapping.get('IDENTITY_VERIFIED',0)==len(records) and dob.get('DOB_VERIFIED',0)==len(records) and collision_pass else 'REVIEW_REQUIRED'
    result={
        'schema':'NEXUS_D1_WIKIDATA_DEMOGRAPHICS_PROBE_RESULT_V2',
        'protocolVersion':'1.1','status':status,'declaredUse':'CURRENT_PROBE','capturedAt':now(),
        'sourceV1':{'path':str(source_path),'sha256':sha(source_bytes),'status':source.get('status'),'capturedAt':source.get('capturedAt')},
        'rules':{'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'contextClubMatching':'normalized exact Wikidata club label/alias only','computedAgeDerived':False,'currentRetrievalImpliesHistoricalAsOf':False,'trainingPromotionGranted':False},
        'summary':{'subjects':len(records),'mappingStatus':mapping,'dobStatus':dob,'contextResolutionFailures':failures,'knownProviderIdReuseRegressionPass':collision_pass},
        'records':records,
    }
    (root/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    files=[]
    for p in sorted(x for x in root.rglob('*') if x.is_file() and x.name!='MANIFEST.json'):
        b=p.read_bytes(); files.append({'path':str(p.relative_to(root)),'size':len(b),'sha256':sha(b)})
    digest=hashlib.sha256('\n'.join(f"{x['path']}\t{x['size']}\t{x['sha256']}" for x in files).encode()).hexdigest()
    (root/'MANIFEST.json').write_text(json.dumps({'schema':'NEXUS_D1_WIKIDATA_DEMOGRAPHICS_PROBE_MANIFEST_V2','generatedAt':now(),'files':files,'fileCount':len(files),'canonicalContentSha256':digest},indent=2)+'\n')
    print(json.dumps(result['summary'],indent=2))

if __name__=='__main__': main()
