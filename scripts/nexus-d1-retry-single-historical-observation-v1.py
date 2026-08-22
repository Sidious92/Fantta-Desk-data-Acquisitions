#!/usr/bin/env python3
import json,re,html,hashlib,time,unicodedata
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import quote
from datetime import datetime,timezone
SRC=Path('.nexus-d1-historical-445-observation-demographics-v1-status/RESULT.json')
OUT=Path('data/nexus-d1/historical-445-single-retry-v1'); OUT.mkdir(parents=True,exist_ok=True); (OUT/'raw').mkdir(exist_ok=True)
def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def slug(s):
    s=unicodedata.normalize('NFKD',s or '').encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+','-',s).strip('-') or 'x'
def fetch(u):
    req=Request(u,headers={'User-Agent':'FantaNexus-D1/1.1','Accept':'text/html,*/*;q=0.8'})
    with urlopen(req,timeout=45) as r: return r.status,r.geturl(),r.read()
def parse(body):
    t=body.decode('utf-8','replace')
    m=re.search(r'Nato il\s*</[^>]+>\s*<[^>]+>\s*([^<]+)',t,re.I)
    if not m: m=re.search(r'Nato il[^0-9]{0,120}(\d{1,2}[\/.-]\d{1,2}[\/.-]\d{4})',t,re.I)
    raw=html.unescape(m.group(1)).strip() if m else ''
    dm=re.search(r'(\d{1,2})[\/.-](\d{1,2})[\/.-](\d{4})',raw)
    dob=f'{dm.group(3)}-{int(dm.group(2)):02d}-{int(dm.group(1)):02d}' if dm else None
    fm=re.search(r'<h1[^>]*>(.*?)</h1>',t,re.I|re.S); full=re.sub('<[^>]+>',' ',html.unescape(fm.group(1))) if fm else None; full=re.sub(r'\s+',' ',full or '').strip()
    can=re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)',t,re.I)
    return full,dob,html.unescape(can.group(1)) if can else None
s=json.loads(SRC.read_text()); failed=[r for r in s['records'] if r.get('status')=='OBSERVATION_BINDING_FAILED']
if len(failed)!=1: raise SystemExit(f'EXPECTED_1_FAILED_GOT_{len(failed)}')
r=failed[0]; season=r['season'].replace('/','-'); pid=r['fantacalcioPlayerId']; nm=r['observedName']; u=f'https://www.fantacalcio.it/serie-a/squadre/x/{quote(slug(nm))}/{pid}/{season}'
rec={'sourceGlobalIndex':r['globalIndex'],'fantacalcioPlayerId':pid,'season':r['season'],'observedName':nm,'requestedUrl':u}
try:
    st,final,b=fetch(u); p=OUT/'raw'/f'fc{pid}--{season}.html'; p.write_bytes(b); full,dob,can=parse(b); rec.update({'httpStatus':st,'finalUrl':final,'canonicalUrl':can,'fullName':full,'dateOfBirth':dob,'rawPath':str(p.relative_to(OUT)),'rawSha256':hashlib.sha256(b).hexdigest(),'rawBytes':len(b)}); rec['exactSeasonPlayerIdBound']=bool(can and f'/{pid}/{season}' in can); rec['status']='OBSERVATION_DEMOGRAPHICS_VERIFIED_ON_TARGETED_RETRY' if rec['exactSeasonPlayerIdBound'] and full and dob else 'SOURCE_NO_COVERAGE_OR_BINDING_FAILED'
except Exception as e:
    rec.update({'status':'SOURCE_NO_COVERAGE_OR_BINDING_FAILED','errorType':type(e).__name__,'detail':str(e)})
res={'schema':'NEXUS_D1_HISTORICAL_SINGLE_OBSERVATION_RETRY_V1','protocolVersion':'1.1','status':'PASS','capturedAt':now(),'record':rec,'governance':{'onlyPreviouslyFailedObservationRequested':True,'providerIdUsedAsGlobalPersonKey':False,'nameSearchUsed':False,'fuzzyMatchingUsed':False,'computedAgeDerived':False,'f1Started':False,'d2Started':False}}
b=(json.dumps(res,ensure_ascii=False,indent=2)+'\n').encode(); (OUT/'RESULT.json').write_bytes(b); (OUT/'MANIFEST.json').write_text(json.dumps({'schema':'NEXUS_D1_HISTORICAL_SINGLE_OBSERVATION_RETRY_MANIFEST_V1','status':'PASS','resultSha256':hashlib.sha256(b).hexdigest(),'resultBytes':len(b),'governance':res['governance']},indent=2)+'\n'); print(json.dumps(rec,indent=2))