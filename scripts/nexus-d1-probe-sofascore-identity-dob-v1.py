#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, time, traceback, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

UA='FantaNexus-D1/1.1 (private scientific source-contract probe)'
RETRYABLE={429,500,502,503,504}

PROBES=[
    {'lookupName':'Patric','club':'Lazio'},
    {'lookupName':'Bremer','club':'Juventus'},
    {'lookupName':"N'Dicka",'club':'Roma'},
    {'lookupName':'Demba Thiam','club':'Monza'},
]

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b): return hashlib.sha256(b).hexdigest()
def norm(s):
    s=unicodedata.normalize('NFKD', str(s or '')).encode('ascii','ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+',' ',s).strip()

def fetch_json(url, attempts=6):
    last=None
    for i in range(attempts):
        try:
            req=Request(url,headers={'User-Agent':UA,'Accept':'application/json'})
            with urlopen(req,timeout=30) as r:
                b=r.read(); return r.status,dict(r.headers.items()),b,json.loads(b)
        except HTTPError as e:
            last=e
            if e.code not in RETRYABLE: raise
        except (URLError,TimeoutError) as e: last=e
        time.sleep(min(20,1.5*(2**i)))
    raise last

def player_entities(obj):
    out=[]
    for r in (obj.get('results') or []):
        typ=str(r.get('type') or '').lower()
        ent=r.get('entity') if isinstance(r.get('entity'),dict) else r
        if typ=='player' or ('player' in r and isinstance(r['player'],dict)):
            if isinstance(r.get('player'),dict): ent=r['player']
            if isinstance(ent,dict): out.append(ent)
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',required=True); args=ap.parse_args()
    out=Path(args.output); raw=out/'raw'; raw.mkdir(parents=True,exist_ok=True)
    records=[]; failures=[]
    for i,p in enumerate(PROBES):
        rec={'probe':p,'identityAccepted':False}
        try:
            u='https://www.sofascore.com/api/v1/search/all?q='+quote(p['lookupName'])
            st,h,b,j=fetch_json(u); sp=raw/f'{i:02d}--search.json'; sp.write_bytes(b)
            ents=player_entities(j)
            rec['search']={'url':u,'httpStatus':st,'rawPath':str(sp.relative_to(out)),'rawSha256':sha(b),'playerResults':len(ents)}
            candidates=[]
            for e in ents:
                pid=e.get('id')
                if pid is None: continue
                du=f'https://www.sofascore.com/api/v1/player/{pid}'
                st2,h2,b2,j2=fetch_json(du); dp=raw/f'{i:02d}--player-{pid}.json'; dp.write_bytes(b2)
                pl=j2.get('player') or {}
                names=[pl.get('name'),pl.get('shortName'),pl.get('firstName'),pl.get('lastName')]
                exact_name=norm(p['lookupName']) in {norm(x) for x in names if x}
                team=(pl.get('team') or {}).get('name') or (e.get('team') or {}).get('name')
                exact_team=norm(team)==norm(p['club'])
                dobts=pl.get('dateOfBirthTimestamp')
                dob=None
                if isinstance(dobts,(int,float)):
                    dob=datetime.fromtimestamp(dobts,tz=timezone.utc).date().isoformat()
                candidates.append({'playerId':pid,'detailUrl':du,'rawPath':str(dp.relative_to(out)),'rawSha256':sha(b2),'names':[x for x in names if x],'team':team,'exactNameOrShortName':exact_name,'exactTeam':exact_team,'dateOfBirthTimestamp':dobts,'dateOfBirthUtcDate':dob})
                time.sleep(0.1)
            accepted=[c for c in candidates if c['exactNameOrShortName'] and c['exactTeam']]
            rec['candidates']=candidates
            rec['acceptedCandidates']=accepted
            if len(accepted)==1 and accepted[0]['dateOfBirthUtcDate']:
                rec['status']='CONTRACT_PASS'; rec['identityAccepted']=True; rec['dateOfBirth']=accepted[0]['dateOfBirthUtcDate']
            elif len(accepted)==1:
                rec['status']='IDENTITY_PASS_DOB_NOT_OBSERVED'; rec['identityAccepted']=True
            elif len(accepted)>1:
                rec['status']='IDENTITY_AMBIGUOUS'
            else:
                rec['status']='NO_EXACT_NAME_TEAM_MATCH'
            records.append(rec)
        except Exception as exc:
            failures.append({'probe':p,'errorType':type(exc).__name__,'detail':str(exc),'traceback':traceback.format_exc()})
    passed=sum(r['status']=='CONTRACT_PASS' for r in records)
    identity=sum(r.get('identityAccepted') for r in records)
    status='PASS' if not failures and passed>=2 and identity>=2 else 'INSUFFICIENT_EVIDENCE'
    result={'schema':'NEXUS_D1_SOFASCORE_IDENTITY_DOB_SEMANTICS_PROBE_V1','protocolVersion':'1.1','status':status,'capturedAt':now(),'authoritySurface':'SofaScore public structured web API','searchEndpoint':'https://www.sofascore.com/api/v1/search/all?q={term}','playerEndpoint':'https://www.sofascore.com/api/v1/player/{id}','acceptance':{'name':'exact normalized equality against provider name or shortName only','club':'exact normalized equality against provider current team name','fuzzyMatchingUsed':False,'dobUsedForIdentitySelection':False,'datePrecision':'DAY from dateOfBirthTimestamp interpreted UTC','ageOnlyAccepted':False,'yearOnlyAccepted':False},'summary':{'subjectsExpected':len(PROBES),'subjectsCompleted':len(records),'contractPass':passed,'identityAccepted':identity,'technicalFailures':len(failures)},'technicalFailures':failures,'records':records,'governance':{'subjectsResolvedIntoD1':False,'secondPassCasesMutated':False,'computedAgeDerived':False,'trainingPromotionGranted':False,'f1Started':False,'d2Started':False}}
    (out/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    files=[]
    for p in sorted(x for x in out.rglob('*') if x.is_file()):
        b=p.read_bytes(); files.append({'path':str(p.relative_to(out)),'size':len(b),'sha256':sha(b)})
    manifest={'schema':'NEXUS_D1_SOFASCORE_IDENTITY_DOB_SEMANTICS_PROBE_MANIFEST_V1','generatedAt':result['capturedAt'],'status':status,'files':files,'fileCount':len(files),'canonicalContentSha256':sha('\n'.join(f"{x['path']}\t{x['size']}\t{x['sha256']}" for x in files).encode()),'governance':result['governance']}
    (out/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(result['summary'],indent=2))

if __name__=='__main__': main()
