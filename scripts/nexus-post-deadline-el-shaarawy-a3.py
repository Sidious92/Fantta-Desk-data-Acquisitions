from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

import importlib.util
BASE_PATH = Path(__file__).with_name('nexus-post-deadline-29-domestic-history-recovery-v1.py')
spec = importlib.util.spec_from_file_location('post29_v1', BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError('cannot load v1 helpers')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

OUT=Path('/tmp/nexus-post-deadline-el-shaarawy-a3')
RAW=OUT/'raw'
OUT.mkdir(parents=True,exist_ok=True); RAW.mkdir(parents=True,exist_ok=True)
PLAYER_ID=795
PROFILE='https://www.fantacalcio.it/serie-a/squadre/genoa/el-shaarawy/795'


def norm(v: Any) -> str:
    t=unicodedata.normalize('NFKD',str(v or ''))
    t=''.join(c for c in t if not unicodedata.combining(c)).lower()
    t=t.replace("'",' ').replace('’',' ')
    return ' '.join(re.findall(r'[a-z0-9]+',t))


def slugify(v: str) -> str:
    return '-'.join(norm(v).split())


def evidence_strings(raw: bytes) -> list[str]:
    soup=BeautifulSoup(raw.decode('utf-8','replace'),'html.parser')
    vals=[]
    if soup.title and soup.title.get_text(strip=True): vals.append(soup.title.get_text(' ',strip=True))
    for sel in ['meta[property="og:title"]','meta[name="twitter:title"]','h1','h2']:
        for node in soup.select(sel):
            value=node.get('content') if node.name=='meta' else node.get_text(' ',strip=True)
            if value: vals.append(str(value))
    seen=[]
    for v in vals:
        if 'shaarawy' in norm(v) and v not in seen:
            seen.append(v)
    return seen


def candidate_slugs(evidence: list[str]) -> list[str]:
    out=['el-shaarawy']
    for e in evidence:
        n=norm(e)
        words=n.split()
        for i,w in enumerate(words):
            if w!='shaarawy': continue
            start=max(0,i-3)
            for j in range(start,i+1):
                seq=words[j:i+1]
                if 'el' in seq and len(seq)<=4:
                    s='-'.join(seq)
                    if s not in out: out.append(s)
    return out[:12]


def player_url(slug: str) -> str:
    q=urllib.parse.urlencode({'fields':b.PLAYER_FIELDS,'lang':'es'},safe='*,()')
    return f'https://cf.biwenger.com/api/v2/players/serie-a/{urllib.parse.quote(slug)}?{q}'


def main() -> None:
    st,raw,err=b.request_bytes(PROFILE)
    if st!=200 or not raw:
        raise RuntimeError(f'Fantacalcio profile fetch failed {st} {err}')
    psha=b.sha256(raw); (RAW/f'fantacalcio-profile-{psha[:12]}.html').write_bytes(raw)
    evidence=evidence_strings(raw)
    slugs=candidate_slugs(evidence)
    probes=[]
    accepted=[]
    for slug in slugs:
        url=player_url(slug)
        st,body,err=b.request_bytes(url,attempts=3)
        rec={'slugCandidate':slug,'url':url,'httpStatus':st,'error':err}
        if st==200 and body:
            try:
                payload=b.parse_json(body); data=payload.get('data') if isinstance(payload,dict) else None
                if isinstance(data,dict):
                    name=str(data.get('name') or '')
                    resp_slug=str(data.get('slug') or '')
                    tokens=set(norm(name).split()) | set(norm(resp_slug.replace('-',' ')).split())
                    identity_ok={'el','shaarawy'} <= tokens
                    rec.update({'providerId':data.get('id'),'providerName':name,'providerSlug':resp_slug,'birthday':data.get('birthday'),'identityTokensOk':identity_ok,'seasonReferences':b.season_refs(payload)})
                    if identity_ok:
                        accepted.append(rec)
                    digest=b.sha256(body); rec['sha256']=digest; (RAW/f'provider-{slug}-{digest[:12]}.json').write_bytes(body)
            except Exception as exc:
                rec['parseError']=repr(exc)
        probes.append(rec)
    uniq={str(r.get('providerId')):r for r in accepted if r.get('providerId') is not None}
    if len(uniq)!=1:
        raise RuntimeError(f'A3 fail-closed accepted provider identities={len(uniq)} probes={probes}')
    selected=next(iter(uniq.values()))
    meta={
        'playerId':PLAYER_ID,'name':'El Shaarawy','club':'Genoa','classicRole':'C','identityStatus':'RESOLVED_SAFE_A3',
        'identityMethod':'OFFICIAL_FANTACALCIO_PROFILE_SLUG_TO_UNIQUE_BIWENGER_IDENTITY_TOKEN_PROBE',
        'providerId':int(selected['providerId']),'providerName':selected['providerName'],'providerSlug':selected['providerSlug'],
        'birthday':selected.get('birthday'),'fetchStatus':'OK','seasonReferences':selected.get('seasonReferences') or [],
    }
    tasks,zero,unknown=b.build_tasks([{**meta,'identityStatus':'RESOLVED_SAFE'}])
    if unknown:
        raise RuntimeError(f'unclassified competition {dict(unknown)}')
    results=[b.fetch_history(t) for t in tasks]
    bad=[r for r in results if r.get('fetchStatus')!='OK' or not r.get('e2ePass')]
    if bad:
        raise RuntimeError(f'A3 history gap {bad}')
    history=[]
    for res in results:
        for report in res.get('reports') or []:
            history.append({'nexusPlayerId':PLAYER_ID,'nexusName':'El Shaarawy','classicRole':'C','birthday':meta.get('birthday'),
                'season':{'id':res['seasonId'],'name':res['season']},'competition':{'id':res.get('competitionId'),'name':res.get('competitionName'),'slug':res['competitionSlug']},
                'historicalPlayerId':res.get('historicalPlayerId'),'playerSlug':res.get('playerSlug'),
                'source':{'url':res['url'],'sha256':res['sha256'],'provenance':'PUBLIC_RUNNER_NETWORK_POST_DEADLINE_A3'},'report':report})
    all_minutes=all(isinstance(r['report'].get('rawStats'),dict) and 'minutesPlayed' in r['report']['rawStats'] for r in history)
    summary={'schema':'NEXUS_POST_DEADLINE_EL_SHAARAWY_A3_V1','status':'PASS_A3_EL_SHAARAWY_RESOLVED',
        'profileSha256':psha,'profileEvidenceStrings':evidence,'probedSlugs':slugs,'providerId':meta['providerId'],'providerName':meta['providerName'],'providerSlug':meta['providerSlug'],
        'historyTasks':len(tasks),'historyTaskPass':len(results),'zeroGameReferencesNotSynthesized':zero,'historyRows':len(history),'allHistoryRowsHaveMinutesPlayed':all_minutes,
        'scientificBoundary':{'predictionValuesUsed':False,'fuzzySimilarityUsed':False,'manualProviderIdOverrideUsed':False,'modelFitPerformed':False,'trainingDataModified':False,'predictiveEngineModified':False,'decisionLayerModified':False},
        'nextGate':'COMBINE A2 28 PLUS A3 1 AS EXACT 29/29 POST-DEADLINE IDENTITY/HISTORY AUTHORITY'}
    if not all_minutes: raise RuntimeError('minutes schema failed')
    for name,obj in [('summary.json',summary),('profile-evidence.json',{'strings':evidence,'slugs':slugs}),('probes.json',probes),('identity-a3.json',meta),('fetch-results-a3.json',results),('history-rows-a3.json',history)]:
        (OUT/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))

if __name__=='__main__': main()
