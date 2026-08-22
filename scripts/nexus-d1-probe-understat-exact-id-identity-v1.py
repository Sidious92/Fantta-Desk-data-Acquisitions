#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re,time,traceback
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError

UA='FantaNexus-D1/1.1 (private scientific identity-demographics audit)'
PROBES=[('1204','Patric'),('6960','Bremer'),('6976','Demba Thiam'),('8182','cross-scope-known')]

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b): return hashlib.sha256(b).hexdigest()
def clean(s): return re.sub(r'\s+',' ',re.sub(r'<[^>]+>',' ',s)).strip()

def fetch(url):
    req=Request(url,headers={'User-Agent':UA,'Accept':'text/html,*/*;q=0.8'})
    with urlopen(req,timeout=45) as r: return r.status,dict(r.headers.items()),r.read(),r.geturl()

def main():
    out=Path('.nexus-d1-understat-exact-id-probe-v1/output'); raw=out/'raw'; raw.mkdir(parents=True,exist_ok=True)
    recs=[]; fails=[]
    for i,(pid,label) in enumerate(PROBES):
        u=f'https://understat.com/player/{pid}'
        try:
            st,h,b,fu=fetch(u); p=raw/f'{i:02d}--understat-{pid}.html'; p.write_bytes(b); t=b.decode('utf-8',errors='replace')
            title=None
            m=re.search(r'<title[^>]*>(.*?)</title>',t,re.I|re.S)
            if m: title=clean(m.group(1))
            h1=None
            m=re.search(r'<h1[^>]*>(.*?)</h1>',t,re.I|re.S)
            if m: h1=clean(m.group(1))
            birth_tokens=sorted(set(re.findall(r'(?i)\b(?:birth(?:day|date)?|dateofbirth|dob)\b',t)))
            recs.append({'understatPlayerId':pid,'label':label,'requestedUrl':u,'finalUrl':fu,'httpStatus':st,'rawPath':str(p),'rawBytes':len(b),'rawSha256':sha(b),'title':title,'h1':h1,'birthLikeTokenCount':len(birth_tokens),'birthLikeTokens':birth_tokens,'exactIdRequestBinding':fu.rstrip('/').endswith('/player/'+pid)})
        except Exception as e:
            fails.append({'understatPlayerId':pid,'errorType':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc()})
        time.sleep(.2)
    usable=sum(1 for r in recs if r['httpStatus']==200 and r['exactIdRequestBinding'] and (r.get('title') or r.get('h1')))
    status='PASS' if len(recs)==4 and not fails and usable==4 else 'INSUFFICIENT_EVIDENCE'
    result={'schema':'NEXUS_D1_UNDERSTAT_EXACT_ID_IDENTITY_PROBE_V1','protocolVersion':'1.1','status':status,'capturedAt':now(),'summary':{'subjectsExpected':4,'subjectsFetched':len(recs),'usableExactIdIdentityPages':usable,'technicalFailures':len(fails)},'rules':{'identityResolvedIntoD1':False,'providerIdUsedAsGlobalPersonKey':False,'nameOnlyMatchingUsed':False,'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'computedAgeDerived':False,'f1Started':False,'d2Started':False},'records':recs,'technicalFailures':fails}
    (out/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result['summary'],indent=2))
if __name__=='__main__': main()
