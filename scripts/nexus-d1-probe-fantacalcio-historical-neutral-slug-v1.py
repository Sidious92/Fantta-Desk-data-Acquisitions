#!/usr/bin/env python3
import hashlib,html,json,re,time,traceback,unicodedata
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen

UA='Mozilla/5.0 FantaNexus-D1/1.1 private-scientific-audit'
PROBES=[('2015-16','2','Merelli'),('2015-16','21',"D'Alessandro"),('2016-17','1','Bassi'),('2016-17','10','Cherubin')]
MONTHS={'gen':1,'feb':2,'mar':3,'apr':4,'mag':5,'giu':6,'lug':7,'ago':8,'set':9,'ott':10,'nov':11,'dic':12}

def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b):return hashlib.sha256(b).hexdigest()
def clean(s):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def fetch(u):
 req=Request(u,headers={'User-Agent':UA,'Accept':'text/html,*/*;q=0.8','Accept-Language':'it-IT,it;q=0.9'})
 with urlopen(req,timeout=45) as r:return r.status,dict(r.headers.items()),r.read(),r.geturl()
def h1(t):
 m=re.search(r'<h1[^>]*>(.*?)</h1>',t,re.I|re.S);return clean(m.group(1)) if m else None
def canonical(t):
 for p in [r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']canonical["\']']:
  m=re.search(p,t,re.I)
  if m:return html.unescape(m.group(1))
def dob(t):
 vals=set();plain=clean(t)
 for d,m,y in re.findall(r'\bNato\s+il\s+(\d{1,2})\s+([A-Za-zÀ-ÿ]{3,10})\s+(\d{4})\b',plain,re.I):
  k=unicodedata.normalize('NFKD',m).encode('ascii','ignore').decode().lower()[:3]
  if k in MONTHS:vals.add(f'{int(y):04d}-{MONTHS[k]:02d}-{int(d):02d}')
 return sorted(vals)

def main():
 out=Path('.nexus-d1-fantacalcio-historical-neutral-slug-probe-v1/output');raw=out/'raw';raw.mkdir(parents=True,exist_ok=True);rows=[];fails=[]
 for i,(season,pid,label) in enumerate(PROBES):
  u=f'https://www.fantacalcio.it/serie-a/squadre/x/x/{pid}/{season}'
  try:
   st,h,b,fu=fetch(u);p=raw/f'{i:02d}--{season}--fc-{pid}.html';p.write_bytes(b);t=b.decode('utf-8',errors='replace');can=canonical(t);nm=h1(t);dates=dob(t);keyok=('/'+pid+'/') in ((can or fu)+'/') and season in (can or fu)
   rows.append({'season':season,'fantacalcioPlayerId':pid,'label':label,'requestedUrl':u,'finalUrl':fu,'canonicalUrl':can,'httpStatus':st,'exactSeasonPlayerIdBound':keyok,'fullName':nm,'dobCandidates':dates,'rawPath':str(p),'rawSha256':sha(b),'rawBytes':len(b)})
  except Exception as e:fails.append({'season':season,'fantacalcioPlayerId':pid,'errorType':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc()})
  time.sleep(.2)
 passed=sum(1 for r in rows if r['httpStatus']==200 and r['exactSeasonPlayerIdBound'] and r['fullName'] and len(r['dobCandidates'])==1)
 status='PASS' if not fails and len(rows)==4 and passed==4 else 'INSUFFICIENT_EVIDENCE'
 result={'schema':'NEXUS_D1_FANTACALCIO_HISTORICAL_NEUTRAL_SLUG_ROUTING_PROBE_V1','protocolVersion':'1.1','status':status,'capturedAt':now(),'summary':{'expected':4,'fetched':len(rows),'exactObservationPass':passed,'technicalFailures':len(fails)},'semantics':{'providerObservationKey':['Fantacalcio','season','fantacalcioPlayerId'],'neutralSeoSlugsAccepted':status=='PASS','providerIdUsedAsGlobalPersonKey':False,'nameSearchUsed':False,'fuzzyMatchingUsed':False},'records':rows,'technicalFailures':fails,'governance':{'subjectsMutated':False,'computedAgeDerived':False,'f1Started':False,'d2Started':False}}
 (out/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result['summary'],indent=2))
if __name__=='__main__':main()
