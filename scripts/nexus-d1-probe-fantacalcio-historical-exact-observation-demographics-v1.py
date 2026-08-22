#!/usr/bin/env python3
from __future__ import annotations
import hashlib,html,json,re,time,traceback,unicodedata
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,urlopen

UA='Mozilla/5.0 FantaNexus-D1/1.1 private-scientific-audit'
PROBES=[
 ('2015-16','2','Atalanta','Merelli'),
 ('2015-16','21','Atalanta',"D'Alessandro"),
 ('2016-17','1','Atalanta','Bassi'),
 ('2016-17','10','Bologna','Cherubin'),
]
MONTHS={'gen':1,'feb':2,'mar':3,'apr':4,'mag':5,'giu':6,'lug':7,'ago':8,'set':9,'ott':10,'nov':11,'dic':12}

def now():return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b):return hashlib.sha256(b).hexdigest()
def slug(s):
 s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode().lower();return re.sub(r'[^a-z0-9]+','-',s).strip('-') or 'x'
def norm(s):
 s=unicodedata.normalize('NFKD',str(s)).encode('ascii','ignore').decode().lower();return re.sub(r'[^a-z0-9]+',' ',s).strip()
def clean(s):return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',s))).strip()
def fetch(u):
 req=Request(u,headers={'User-Agent':UA,'Accept':'text/html,*/*;q=0.8','Accept-Language':'it-IT,it;q=0.9,en;q=0.7'})
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
def club_near(t,name,club):
 p=norm(clean(t));n=norm(name or '');c=norm(club or '');i=p.find(n) if n else -1
 return i>=0 and c in p[i:i+800]

def main():
 out=Path('.nexus-d1-fantacalcio-historical-observation-probe-v1/output');raw=out/'raw';raw.mkdir(parents=True,exist_ok=True);recs=[];fails=[]
 for i,(season,pid,club,name) in enumerate(PROBES):
  u=f'https://www.fantacalcio.it/serie-a/squadre/{slug(club)}/{slug(name)}/{pid}/{season}'
  try:
   st,h,b,fu=fetch(u);p=raw/f'{i:02d}--{season}--fc-{pid}.html';p.write_bytes(b);t=b.decode('utf-8',errors='replace');can=canonical(t);nm=h1(t);dates=dob(t);idok=('/'+pid+'/') in ((can or fu)+'/');seasonok=season in (can or fu);clubok=club_near(t,nm,club)
   recs.append({'season':season,'fantacalcioPlayerId':pid,'expectedClub':club,'sourceName':name,'requestedUrl':u,'finalUrl':fu,'canonicalUrl':can,'httpStatus':st,'exactSeasonPlayerIdBound':idok and seasonok,'expectedClubConfirmedNearIdentity':clubok,'fullName':nm,'dobCandidates':dates,'rawPath':str(p),'rawBytes':len(b),'rawSha256':sha(b)})
  except Exception as e:fails.append({'season':season,'fantacalcioPlayerId':pid,'errorType':type(e).__name__,'detail':str(e),'traceback':traceback.format_exc()})
  time.sleep(.25)
 passed=sum(1 for r in recs if r['httpStatus']==200 and r['exactSeasonPlayerIdBound'] and r['expectedClubConfirmedNearIdentity'] and r['fullName'] and len(r['dobCandidates'])==1)
 status='PASS' if len(recs)==4 and not fails and passed==4 else 'INSUFFICIENT_EVIDENCE'
 result={'schema':'NEXUS_D1_FANTACALCIO_HISTORICAL_EXACT_OBSERVATION_DEMOGRAPHICS_PROBE_V1','protocolVersion':'1.1','status':status,'capturedAt':now(),'summary':{'observationsExpected':4,'observationsFetched':len(recs),'exactSeasonIdClubDobPass':passed,'technicalFailures':len(fails)},'semantics':{'identityBinding':'HISTORICAL_SEASON_PLUS_FANTACALCIO_PLAYER_ID_PLUS_CLUB_CONTEXT','providerIdUsedAsGlobalHistoricalPersonKey':False,'datePrecision':'DAY','nameSearchUsed':False,'fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False},'records':recs,'technicalFailures':fails,'governance':{'historicalPersonsAutoMerged':False,'computedAgeDerived':False,'f1Started':False,'d2Started':False}}
 (out/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result['summary'],indent=2))
if __name__=='__main__':main()
