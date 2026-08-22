#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import time
import traceback
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

UA = 'FantaNexus-D1/1.1 (private scientific identity-demographics audit)'
RETRYABLE = {429, 500, 502, 503, 504}


def now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def sha256(b: bytes):
    return hashlib.sha256(b).hexdigest()


def fetch(url: str, attempts: int = 8):
    last = None
    for i in range(attempts):
        try:
            req = Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,application/json;q=0.9,*/*;q=0.8'})
            with urlopen(req, timeout=45) as r:
                return r.status, dict(r.headers.items()), r.read(), r.geturl()
        except HTTPError as e:
            last = e
            if e.code not in RETRYABLE:
                raise
        except (URLError, TimeoutError) as e:
            last = e
        time.sleep(min(30, 1.5 * (2 ** i)))
    raise last


def exact_dates_from_statements(stmts):
    out = set()
    for s in stmts or []:
        t = s.get('time')
        p = s.get('precision')
        if isinstance(t, str) and p == 11:
            m = re.match(r'^\+(\d{4}-\d{2}-\d{2})T', t)
            if m:
                out.add(m.group(1))
    return sorted(out)


def extract_bday_dates(text: str):
    patterns = [
        r'class=["\'][^"\']*\bbday\b[^"\']*["\'][^>]*>\s*(\d{4}-\d{2}-\d{2})\s*<',
        r'<time[^>]+datetime=["\'](\d{4}-\d{2}-\d{2})(?:T[^"\']*)?["\'][^>]*class=["\'][^"\']*(?:bday|birth)[^"\']*["\']',
    ]
    vals = set()
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.I):
            vals.add(m.group(1))
    return sorted(vals)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--subjects', required=True)
    ap.add_argument('--output', required=True)
    args = ap.parse_args()

    source_path = Path(args.subjects)
    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes)
    if source.get('status') != 'PASS':
        raise RuntimeError('SECOND_PASS_SURFACE_NOT_PASS')

    selected = []
    for scope_key in ('currentOpen', 'historicalOpen'):
        for r in source.get(scope_key) or []:
            if r.get('mappingStatus') == 'IDENTITY_VERIFIED' and r.get('dateOfBirthStatus') == 'DOB_CONFLICT':
                qid = r.get('wikidataItemId')
                if not qid:
                    raise RuntimeError(f'VERIFIED_CONFLICT_WITHOUT_QID:{r.get("subjectId")}')
                selected.append(r)
    if len(selected) != 47:
        raise RuntimeError(f'EXPECTED_47_CONFLICT_RECORDS_GOT_{len(selected)}')

    by_qid = {}
    for r in selected:
        qid = r['wikidataItemId']
        item = by_qid.setdefault(qid, {'qid': qid, 'sourceRecords': [], 'conflictDates': set()})
        item['sourceRecords'].append({
            'scope': r.get('scope'),
            'subjectId': r.get('subjectId'),
            'firstPassSubjectLocator': r.get('firstPassSubjectLocator'),
            'lookupName': r.get('lookupName'),
            'bridgePersonKey': r.get('bridgePersonKey'),
        })
        item['conflictDates'].update(exact_dates_from_statements(r.get('allDobStatements')))
    if len(by_qid) != 46:
        raise RuntimeError(f'EXPECTED_46_UNIQUE_QIDS_GOT_{len(by_qid)}')

    out = Path(args.output)
    raw = out / 'raw'
    raw.mkdir(parents=True, exist_ok=True)
    records = []
    failures = []

    for idx, qid in enumerate(sorted(by_qid)):
        base = by_qid[qid]
        rec = {
            'wikidataItemId': qid,
            'sourceRecords': base['sourceRecords'],
            'conflictDates': sorted(base['conflictDates']),
            'identityBindingMethod': 'EXACT_VERIFIED_WIKIDATA_QID_TO_EXACT_WIKIPEDIA_SITELINK',
            'dobUsedForIdentitySelection': False,
        }
        try:
            entity_url = f'https://www.wikidata.org/wiki/Special:EntityData/{qid}.json'
            st, headers, body, final_url = fetch(entity_url)
            ep = raw / f'{idx:03d}--{qid}--wikidata.json'
            ep.write_bytes(body)
            entity = json.loads(body)
            e = entity['entities'][qid]
            sitelinks = e.get('sitelinks') or {}
            site = 'itwiki' if 'itwiki' in sitelinks else ('enwiki' if 'enwiki' in sitelinks else None)
            rec['routingEvidence'] = {
                'wikidataEntityUrl': entity_url,
                'rawPath': str(ep.relative_to(out)),
                'rawSha256': sha256(body),
                'sitelinkSite': site,
            }
            if not site:
                rec['status'] = 'SOURCE_NO_COVERAGE'
                rec['wikipediaDob'] = None
                records.append(rec)
                continue
            title = sitelinks[site]['title']
            lang = 'it' if site == 'itwiki' else 'en'
            page_url = f'https://{lang}.wikipedia.org/wiki/{quote(title.replace(" ", "_"), safe="()_,-%")}'
            st2, headers2, page, final_page = fetch(page_url)
            pp = raw / f'{idx:03d}--{qid}--{lang}wiki.html'
            pp.write_bytes(page)
            text = page.decode('utf-8', errors='replace')
            dates = extract_bday_dates(text)
            rec['wikipediaEvidence'] = {
                'site': site,
                'title': title,
                'requestedUrl': page_url,
                'finalUrl': final_page,
                'httpStatus': st2,
                'rawPath': str(pp.relative_to(out)),
                'rawBytes': len(page),
                'rawSha256': sha256(page),
                'exactBdayCandidates': dates,
            }
            if len(dates) == 1:
                d = dates[0]
                rec['wikipediaDob'] = d
                if d in rec['conflictDates']:
                    rec['status'] = 'DOB_CORROBORATED_BY_WIKIPEDIA'
                    rec['corroboratedDate'] = d
                else:
                    rec['status'] = 'DOB_NEW_CONFLICT'
            elif len(dates) == 0:
                rec['status'] = 'DOB_NOT_OBSERVED'
                rec['wikipediaDob'] = None
            else:
                rec['status'] = 'DOB_SOURCE_AMBIGUOUS'
                rec['wikipediaDob'] = None
            records.append(rec)
        except Exception as exc:
            failures.append({
                'wikidataItemId': qid,
                'errorType': type(exc).__name__,
                'detail': str(exc),
                'traceback': traceback.format_exc(),
            })
        time.sleep(0.15)

    counts = Counter(r['status'] for r in records)
    captured = now()
    status = 'PASS' if not failures and len(records) == 46 else 'TECHNICAL_FAILURE_NOT_SCIENTIFIC_MISSINGNESS'
    result = {
        'schema': 'NEXUS_D1_SECOND_PASS_DOB_CONFLICT_WIKIPEDIA_RESULT_V1',
        'protocolVersion': '1.1',
        'status': status,
        'capturedAt': captured,
        'sourceSurface': {
            'path': str(source_path),
            'bytes': len(source_bytes),
            'sha256': sha256(source_bytes),
            'rawConflictRecords': 47,
            'uniqueVerifiedWikidataPersons': 46,
        },
        'rules': {
            'identityBindingExactVerifiedWikidataQid': True,
            'wikipediaPageSelectedOnlyByExactQidSitelink': True,
            'nameSearchUsed': False,
            'fuzzyMatchingUsed': False,
            'dobUsedForIdentitySelection': False,
            'computedAgeDerived': False,
            'dobInferred': False,
            'currentRetrievalImpliesHistoricalAsOf': False,
            'trainingPromotionGranted': False,
            'f1Started': False,
            'd2Started': False,
        },
        'summary': {
            'rawConflictRecords': 47,
            'uniquePersons': 46,
            'recordsCompleted': len(records),
            'statusCounts': dict(sorted(counts.items())),
            'requestFailures': len(failures),
        },
        'requestFailures': failures,
        'records': records,
    }
    (out / 'RESULT.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')

    evidence = []
    for p in sorted(x for x in out.rglob('*') if x.is_file()):
        b = p.read_bytes()
        evidence.append({'path': str(p.relative_to(out)), 'size': len(b), 'sha256': sha256(b)})
    digest = sha256('\n'.join(f"{e['path']}\t{e['size']}\t{e['sha256']}" for e in evidence).encode())
    manifest = {
        'schema': 'NEXUS_D1_SECOND_PASS_DOB_CONFLICT_WIKIPEDIA_MANIFEST_V1',
        'generatedAt': captured,
        'status': status,
        'evidenceFileCount': len(evidence),
        'canonicalEvidenceSha256': digest,
        'evidence': evidence,
        'governance': result['rules'],
    }
    (out / 'MANIFEST.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['summary'], indent=2))
    if status != 'PASS':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
