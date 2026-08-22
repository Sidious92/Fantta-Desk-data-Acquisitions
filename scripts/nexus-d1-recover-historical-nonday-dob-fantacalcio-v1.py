#!/usr/bin/env python3
from __future__ import annotations
import base64,hashlib,html,json,lzma,re,time,traceback,unicodedata
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen

UA='Mozilla/5.0 FantaNexus-D1/1.1 private-scientific-audit'
MONTHS={'gen':1,'feb':2,'mar':3,'apr':4,'mag':5,'giu':6,'lug':7,'ago':8,'set':9,'ott':10,'nov':11,'dic':12}
RETRYABLE={429,500,502,503,504}
def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b):return hashlib.sha256(b).hexdigest()
def season_slug(s):return str(s).replace('/','-')
def clean(s):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def canonical(t):
    for p in [r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']']:
        m=re.search(p,t,re.I)
        if m:return html.unescape(m.group(1))
def parse_h1(t):
    m=re.search(r'<h1[^>]*>(.*?)</h1>',t,re.I|re.S);return clean(m.group(1)) if m else None
def parse_dob(t):
    vals=set();plain=clean(t)
    for d,m,y in re.findall(r'\bNato\s+il\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]{3,10})\s+(\d{4})\b',plain,re.I):
        k=unicodedata.normalize('NFKD',m).encode('ascii','ignore').decode().lower()[:3]
        if k in MONTHS:vals.add(f'{int(y):04d}-{MONTHS[k]:02d}-{int(d):02d}')
    return sorted(vals)
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
        time.sleep(min(20,1.3*(2**i)))
    raise last
def reconstruct(manifest_path):
    m=json.loads(Path(manifest_path).read_text()); parts=[]
    for c in m['payload']['chunks']:
        text=Path(c['path']).read_text().strip(); assert len(text)==c['chars']; assert hashlib.sha256(text.encode()).hexdigest()==c['textSha256']; parts.append(text)
    raw=lzma.decompress(base64.b64decode(''.join(parts),validate=True)); assert hashlib.sha256(raw).hexdigest()==m['payload']['decodedJsonSha256']; return json.loads(raw),m

def main():
    audit=json.loads(Path('data/nexus-d1/dob-precision-audit-v1/RESULT.json').read_text())
    assert audit['status']=='PASS' and audit['current']['nonDayPrecisionCount']==0 and audit['historical']['nonDayPrecisionCount']==6
    surf,sm=reconstruct('data/nexus-d1/historical-resolved-person-subjects-v3-manifest.json')
    by={str(x['understatPlayerId']):x for x in surf['subjects']}
    targets=audit['historical']['nonDayPrecisionRecords']; assert len(targets)==6
    out=Path('.nexus-d1-historical-nonday-dob-fantacalcio-v1/output'); rawdir=out/'raw'; rawdir.mkdir(parents=True,exist_ok=True)
    records=[];fail=[]
    for i,tg in enumerate(targets):
        uid=str(tg['understatPlayerId']); s=by.get(uid)
        if not s: raise RuntimeError(f'UNDERSTAT_TARGET_NOT_IN_D0_SURFACE:{uid}')
        ids=[str(x) for x in s.get('fantacalcioObservationIds') or []]; seasons=[str(x) for x in s.get('seasons') or []]
        if not ids or not seasons: raise RuntimeError(f'NO_EXACT_FC_OBSERVATION_ROUTE:{uid}')
        accepted=[];attempts=[]
        for pid in ids:
            for season in seasons:
                u=f'https://www.fantacalcio.it/serie-a/squadre/x/x/{pid}/{season_slug(season)}'; a={'fantacalcioPlayerId':pid,'season':season,'requestedUrl':u}
                try:
                    st,h,b,fu=fetch(u); a['httpStatus']=st
                    if st==404:a['status']='NO_PAGE_FOR_EXACT_OBSERVATION';attempts.append(a);continue
                    p=rawdir/f'{i:02d}--u{uid}--fc{pid}--{season_slug(season)}.html';p.write_bytes(b);text=b.decode('utf-8',errors='replace');can=canonical(text);nm=parse_h1(text);ds=parse_dob(text);bind=('/'+pid+'/') in ((can or fu)+'/') and season_slug(season) in (can or fu)
                    a.update({'finalUrl':fu,'canonicalUrl':can,'exactSeasonPlayerIdBound':bind,'fullName':nm,'dobCandidates':ds,'rawPath':str(p.relative_to(out)),'rawBytes':len(b),'rawSha256':sha(b)})
                    if bind and len(ds)==1:a['status']='ACCEPTED_EXACT_OBSERVATION';a['dateOfBirth']=ds[0];accepted.append(a)
                    elif not bind:a['status']='OBSERVATION_BINDING_FAILED'
                    elif not ds:a['status']='DOB_NOT_OBSERVED'
                    else:a['status']='DOB_SOURCE_AMBIGUOUS'
                    attempts.append(a)
                except Exception as e:
                    fail.append({'understatPlayerId':uid,'fantacalcioPlayerId':pid,'season':season,'errorType':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc()})
                time.sleep(.12)
        dobs=sorted({x['dateOfBirth'] for x in accepted})
        if len(dobs)==1:status='DOB_VERIFIED_BY_D0_BRIDGE_AND_EXACT_FC_CONSENSUS';dob=dobs[0]
        elif len(dobs)>1:status='DOB_CONFLICT_ACROSS_EXACT_FC_OBSERVATIONS';dob=None
        else:status='DOB_UNRESOLVED_NO_EXACT_FC_DATE';dob=None
        records.append({'subjectId':tg['subjectId'],'understatPlayerId':uid,'bridgePersonKey':tg['bridgePersonKey'],'wikidataItemId':tg['wikidataItemId'],'wikidataNonDayPrecision':tg['precision'],'wikidataRawTime':tg['rawTime'],'status':status,'dateOfBirth':dob,'distinctExactFantacalcioDobValues':dobs,'acceptedObservationCount':len(accepted),'attempts':attempts})
    counts=Counter(x['status'] for x in records); overall='PASS' if not fail and len(records)==6 else 'TECHNICAL_FAILURE_NOT_SCIENTIFIC_MISSINGNESS';cap=now()
    result={'schema':'NEXUS_D1_HISTORICAL_NONDAY_DOB_FANTACALCIO_RESULT_V1','protocolVersion':'1.1','status':overall,'capturedAt':cap,'summary':{'subjects':6,'statusCounts':dict(sorted(counts.items())),'dobVerified':counts.get('DOB_VERIFIED_BY_D0_BRIDGE_AND_EXACT_FC_CONSENSUS',0),'dobConflict':counts.get('DOB_CONFLICT_ACROSS_EXACT_FC_OBSERVATIONS',0),'dobUnresolved':counts.get('DOB_UNRESOLVED_NO_EXACT_FC_DATE',0),'requestFailures':len(fail)},'rules':{'wikidataPrecisionBelow11NeverPromotedToExactDob':True,'identityAuthority':'D0_DERIVED_UNDERSTAT_PERSON_BRIDGE','providerObservationKey':['Fantacalcio','season','fantacalcioPlayerId'],'providerIdUsedAsGlobalPersonKey':False,'nameSearchUsed':False,'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'computedAgeDerived':False,'f1Started':False,'d2Started':False},'requestFailures':fail,'records':records}
    (out/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    evidence=[]
    for p in sorted(x for x in out.rglob('*') if x.is_file()):
        b=p.read_bytes();evidence.append({'path':str(p.relative_to(out)),'size':len(b),'sha256':sha(b)})
    digest=sha('\n'.join(f"{x['path']}\t{x['size']}\t{x['sha256']}" for x in evidence).encode())
    manifest={'schema':'NEXUS_D1_HISTORICAL_NONDAY_DOB_FANTACALCIO_MANIFEST_V1','generatedAt':cap,'status':overall,'evidenceFileCount':len(evidence),'canonicalEvidenceSha256':digest,'evidence':evidence,'governance':result['rules']}
    (out/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['summary'],indent=2))
    if overall!='PASS':raise SystemExit(2)
if __name__=='__main__':main()
