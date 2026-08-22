#!/usr/bin/env python3
from __future__ import annotations
import hashlib,html,json,re,time,traceback,unicodedata
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

UA='Mozilla/5.0 FantaNexus-D1/1.1 private-scientific-audit'
PROBES=[('327','Lazio','Patric'),('2788','Juventus','Bremer'),('4317','Roma',"N'Dicka"),('2857','Genoa','Traore Hj')]
MONTHS={'gen':1,'feb':2,'mar':3,'apr':4,'mag':5,'giu':6,'lug':7,'ago':8,'set':9,'ott':10,'nov':11,'dic':12}

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b): return hashlib.sha256(b).hexdigest()
def slug(s):
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+','-',s).strip('-') or 'x'
def clean_html(s): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def fetch(u):
    req=Request(u,headers={'User-Agent':UA,'Accept':'text/html,*/*;q=0.8','Accept-Language':'it-IT,it;q=0.9,en;q=0.7'})
    with urlopen(req,timeout=45) as r: return r.status,dict(r.headers.items()),r.read(),r.geturl()
def parse_dob(text):
    plain=clean_html(text)
    ms=re.findall(r'\bNato\s+il\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]{3,10})\s+(\d{4})\b',plain,re.I)
    vals=set()
    for d,m,y in ms:
        k=unicodedata.normalize('NFKD',m).encode('ascii','ignore').decode().lower()[:3]
        if k in MONTHS:
            vals.add(f'{int(y):04d}-{MONTHS[k]:02d}-{int(d):02d}')
    return sorted(vals)
def parse_h1(text):
    m=re.search(r'<h1[^>]*>(.*?)</h1>',text,re.I|re.S)
    return clean_html(m.group(1)) if m else None
def canonical(text):
    for pat in [r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']']:
        m=re.search(pat,text,re.I)
        if m:return html.unescape(m.group(1))
    return None

def main():
    out=Path('.nexus-d1-fantacalcio-current-exact-id-probe-v1/output'); raw=out/'raw'; raw.mkdir(parents=True,exist_ok=True)
    recs=[];fails=[]
    for i,(pid,club,name) in enumerate(PROBES):
        u=f'https://www.fantacalcio.it/serie-a/squadre/{slug(club)}/{slug(name)}/{pid}'
        try:
            st,h,b,fu=fetch(u); p=raw/f'{i:02d}--fc-{pid}.html';p.write_bytes(b);t=b.decode('utf-8',errors='replace')
            can=canonical(t); h1=parse_h1(t); dates=parse_dob(t)
            exact=('/'+pid) in (can or fu)
            recs.append({'fantacalcioPlayerId':pid,'expectedClub':club,'sourceLookupName':name,'requestedUrl':u,'finalUrl':fu,'canonicalUrl':can,'httpStatus':st,'exactProviderIdBound':exact,'fullName':h1,'dobCandidates':dates,'rawPath':str(p),'rawBytes':len(b),'rawSha256':sha(b)})
        except Exception as e:
            fails.append({'fantacalcioPlayerId':pid,'errorType':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc()})
        time.sleep(.25)
    passed=sum(1 for r in recs if r['httpStatus']==200 and r['exactProviderIdBound'] and r['fullName'] and len(r['dobCandidates'])==1)
    status='PASS' if not fails and len(recs)==4 and passed==4 else 'INSUFFICIENT_EVIDENCE'
    result={'schema':'NEXUS_D1_FANTACALCIO_CURRENT_EXACT_ID_DEMOGRAPHICS_PROBE_V1','protocolVersion':'1.1','status':status,'capturedAt':now(),'summary':{'subjectsExpected':4,'subjectsFetched':len(recs),'exactIdDobPass':passed,'technicalFailures':len(fails)},'semantics':{'authoritySurface':'Fantacalcio current Serie A player profile','identityBinding':'CURRENT_LISTONE_FANTACALCIO_PLAYER_ID_EXACT','dateSource':'Nato il on exact-ID current player page','datePrecision':'DAY','providerIdUsedAsGlobalHistoricalPersonKey':False,'currentScopeOnly':True,'nameSearchUsed':False,'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False},'records':recs,'technicalFailures':fails,'governance':{'subjectsResolvedIntoD1':False,'secondPassCasesMutated':False,'computedAgeDerived':False,'f1Started':False,'d2Started':False}}
    (out/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['summary'],indent=2))
if __name__=='__main__':main()
