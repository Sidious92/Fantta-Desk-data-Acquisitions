#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,html,json,re,time,traceback,unicodedata
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen

UA='Mozilla/5.0 FantaNexus-D1/1.1 private-scientific-audit'
RETRYABLE={429,500,502,503,504}
MONTHS={'gen':1,'feb':2,'mar':3,'apr':4,'mag':5,'giu':6,'lug':7,'ago':8,'set':9,'ott':10,'nov':11,'dic':12}

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b): return hashlib.sha256(b).hexdigest()
def slug(s):
    s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+','-',s).strip('-') or 'x'
def norm(s):
    s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+',' ',s).strip()
def clean_html(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def fetch(u,attempts=8):
    last=None
    for i in range(attempts):
        try:
            req=Request(u,headers={'User-Agent':UA,'Accept':'text/html,*/*;q=0.8','Accept-Language':'it-IT,it;q=0.9,en;q=0.7'})
            with urlopen(req,timeout=45) as r:return r.status,dict(r.headers.items()),r.read(),r.geturl()
        except HTTPError as e:
            last=e
            if e.code not in RETRYABLE: raise
        except (URLError,TimeoutError) as e:last=e
        time.sleep(min(30,1.4*(2**i)))
    raise last
def parse_dob(text):
    plain=clean_html(text); vals=set()
    for d,m,y in re.findall(r'\bNato\s+il\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]{3,10})\s+(\d{4})\b',plain,re.I):
        k=unicodedata.normalize('NFKD',m).encode('ascii','ignore').decode().lower()[:3]
        if k in MONTHS: vals.add(f'{int(y):04d}-{MONTHS[k]:02d}-{int(d):02d}')
    return sorted(vals)
def parse_h1(text):
    m=re.search(r'<h1[^>]*>(.*?)</h1>',text,re.I|re.S); return clean_html(m.group(1)) if m else None
def canonical(text):
    for pat in [r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']']:
        m=re.search(pat,text,re.I)
        if m:return html.unescape(m.group(1))
    return None
def current_fc_id(r):
    sid=str(r.get('subjectId') or '')
    m=re.fullmatch(r'current-fc-(\d+)',sid)
    if not m: raise RuntimeError(f'CURRENT_SUBJECT_WITHOUT_EXACT_FC_ID:{sid}')
    return m.group(1)
def club_confirmed(text,full_name,club):
    plain=clean_html(text); n=norm(full_name or ''); c=norm(club or '')
    pn=norm(plain)
    if not c:return False
    # Strong local context: expected club within a bounded window following the player's H1/name.
    pos=pn.find(n) if n else -1
    if pos>=0 and c in pn[pos:pos+800]:return True
    return False

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--subjects',required=True);ap.add_argument('--probe',required=True);ap.add_argument('--output',required=True);a=ap.parse_args()
    probe=json.loads(Path(a.probe).read_text())
    if probe.get('status')!='PASS' or (probe.get('summary') or {}).get('exactIdDobPass')!=4:raise RuntimeError('FANTACALCIO_EXACT_ID_PROBE_NOT_PASS')
    sp=Path(a.subjects);sb=sp.read_bytes();src=json.loads(sb)
    if src.get('status')!='PASS':raise RuntimeError('SECOND_PASS_V2_NOT_PASS')
    rows=src.get('currentOpen') or []
    if len(rows)!=127:raise RuntimeError(f'EXPECTED_127_CURRENT_OPEN_GOT_{len(rows)}')
    out=Path(a.output);raw=out/'raw';raw.mkdir(parents=True,exist_ok=True)
    recs=[];fails=[]
    for i,r in enumerate(rows):
        pid=current_fc_id(r);club=(r.get('contextClubs') or [None])[0];lookup=r.get('lookupName') or 'x'
        u=f'https://www.fantacalcio.it/serie-a/squadre/{slug(club)}/{slug(lookup)}/{pid}'
        rec={'scope':'CURRENT_2026_27','subjectId':r.get('subjectId'),'fantacalcioPlayerId':pid,'sourceLookupName':lookup,'expectedCurrentClub':club,'firstPassMappingStatus':r.get('mappingStatus'),'firstPassDobStatus':r.get('dateOfBirthStatus'),'identityBindingMethod':'CURRENT_LISTONE_EXACT_FANTACALCIO_PLAYER_ID_TO_CURRENT_PLAYER_PAGE','providerIdUsedAsGlobalHistoricalPersonKey':False}
        try:
            st,h,b,fu=fetch(u);p=raw/f'{i:03d}--fc-{pid}.html';p.write_bytes(b);t=b.decode('utf-8',errors='replace')
            can=canonical(t);name=parse_h1(t);dates=parse_dob(t);exact=('/'+pid) in (can or fu);club_ok=club_confirmed(t,name,club)
            rec.update({'requestedUrl':u,'finalUrl':fu,'canonicalUrl':can,'httpStatus':st,'exactProviderIdBound':exact,'fullName':name,'dobCandidates':dates,'expectedClubConfirmedNearIdentity':club_ok,'rawPath':str(p.relative_to(out)),'rawBytes':len(b),'rawSha256':sha(b)})
            if not exact:rec['status']='IDENTITY_BINDING_FAILED'
            elif not name:rec['status']='FULL_NAME_NOT_OBSERVED'
            elif not club_ok:rec['status']='CURRENT_CLUB_CONTEXT_UNCONFIRMED'
            elif len(dates)==1:
                rec['status']='CURRENT_IDENTITY_DOB_VERIFIED';rec['dateOfBirth']=dates[0]
            elif len(dates)==0:rec['status']='DOB_NOT_OBSERVED'
            else:rec['status']='DOB_SOURCE_AMBIGUOUS'
            recs.append(rec)
        except Exception as e:
            fails.append({'subjectId':r.get('subjectId'),'fantacalcioPlayerId':pid,'errorType':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc()})
        time.sleep(.18)
    counts=Counter(r['status'] for r in recs);cap=now();status='PASS' if not fails and len(recs)==127 else 'TECHNICAL_FAILURE_NOT_SCIENTIFIC_MISSINGNESS'
    result={'schema':'NEXUS_D1_CURRENT_OPEN_FANTACALCIO_DEMOGRAPHICS_RESULT_V1','protocolVersion':'1.1','status':status,'capturedAt':cap,'sourceSurface':{'path':str(sp),'bytes':len(sb),'sha256':sha(sb),'currentOpenRecords':127},'rules':{'currentListoneExactFantacalcioIdBinding':True,'providerIdUsedAsGlobalHistoricalPersonKey':False,'currentScopeOnly':True,'nameSearchUsed':False,'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'computedAgeDerived':False,'dobInferred':False,'trainingPromotionGranted':False,'f1Started':False,'d2Started':False},'summary':{'subjects':127,'recordsCompleted':len(recs),'statusCounts':dict(sorted(counts.items())),'currentIdentityDobVerified':counts.get('CURRENT_IDENTITY_DOB_VERIFIED',0),'requestFailures':len(fails)},'requestFailures':fails,'records':recs}
    (out/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    evidence=[]
    for p in sorted(x for x in out.rglob('*') if x.is_file()):
        bb=p.read_bytes();evidence.append({'path':str(p.relative_to(out)),'size':len(bb),'sha256':sha(bb)})
    digest=sha('\n'.join(f"{e['path']}\t{e['size']}\t{e['sha256']}" for e in evidence).encode())
    (out/'MANIFEST.json').write_text(json.dumps({'schema':'NEXUS_D1_CURRENT_OPEN_FANTACALCIO_DEMOGRAPHICS_MANIFEST_V1','generatedAt':cap,'status':status,'evidenceFileCount':len(evidence),'canonicalEvidenceSha256':digest,'evidence':evidence,'governance':result['rules']},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['summary'],indent=2))
    if status!='PASS':raise SystemExit(2)
if __name__=='__main__':main()
