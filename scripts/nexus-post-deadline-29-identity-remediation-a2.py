from __future__ import annotations

import concurrent.futures
import importlib.util
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

BASE_PATH = Path(__file__).with_name('nexus-post-deadline-29-domestic-history-recovery-v1.py')
spec = importlib.util.spec_from_file_location('post29_v1', BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError('cannot load v1 helpers')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

OUT = Path('/tmp/nexus-post-deadline-29-identity-remediation-a2')
RAW = OUT / 'raw'
OUT.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)

TEAM_ALIASES = {
    'parma': {'parma','parma calcio'},
}


def norm(v: Any) -> str:
    text = unicodedata.normalize('NFKD', str(v or ''))
    text = ''.join(c for c in text if not unicodedata.combining(c)).lower()
    text = text.replace("'", ' ').replace('’', ' ')
    return ' '.join(re.findall(r'[a-z0-9]+', text))


def current_team_name(row: dict[str, Any], teams: dict[int, dict[str, Any]]) -> str:
    try:
        return str(teams.get(int(row.get('teamID')), {}).get('name') or '')
    except (TypeError, ValueError):
        return ''


def team_matches(target: str, provider: str) -> bool:
    t, p = norm(target), norm(provider)
    if t == p:
        return True
    aliases = TEAM_ALIASES.get(t, {t})
    return p in aliases


def name_support(current: str, provider_row: dict[str, Any]) -> bool:
    cur = norm(current)
    pname = norm(provider_row.get('name'))
    pslug = norm(str(provider_row.get('slug') or '').replace('-', ' '))
    variants = {x for x in (pname, pslug) if x}
    ct = cur.split()
    if not ct:
        return False
    if len(ct) >= 2 and cur in variants:
        return True
    # Single-token Fantacalcio display: require exact token support in provider name/slug.
    if len(ct) == 1:
        token = ct[0]
        return any(token in v.split() for v in variants)
    # Abbreviated display such as "Sarr P." / "Fernandez T." / "Sanchez Ro.":
    # require one full token plus deterministic prefix support for every abbreviated token.
    full = [x for x in ct if len(x) > 2]
    short = [x for x in ct if len(x) <= 2]
    for v in variants:
        vt = v.split()
        if full and not all(x in vt for x in full):
            continue
        if short and not all(any(y.startswith(x) for y in vt) for x in short):
            continue
        if full or short:
            return True
    return False


def resolve(player: dict[str, Any], catalog: list[dict[str, Any]], teams: dict[int, dict[str, Any]]) -> dict[str, Any]:
    supported=[]
    for row in catalog:
        team = current_team_name(row, teams)
        if not team_matches(player['club'], team):
            continue
        if name_support(player['name'], row):
            supported.append((row, team))
    if len(supported) == 1:
        row, team = supported[0]
        return {**player,
            'identityStatus':'RESOLVED_SAFE_A2',
            'identityMethod':'UNIQUE_CURRENT_TEAM_PLUS_DETERMINISTIC_NAME_SUPPORT',
            'providerId':row.get('id'),'providerName':row.get('name'),'providerSlug':row.get('slug'),
            'providerCurrentTeam':team,'candidateCount':1,
        }
    return {**player,
        'identityStatus':'UNRESOLVED_A2' if not supported else 'AMBIGUOUS_A2',
        'identityMethod':None,'providerId':None,'providerName':None,'providerSlug':None,
        'providerCurrentTeam':None,'candidateCount':len(supported),
    }


def main() -> None:
    st, roster_raw, err = b.request_bytes(b.FANTACALCIO_URL)
    if st != 200 or not roster_raw:
        raise RuntimeError(f'Fantacalcio fetch failed {st} {err}')
    targets, roster_sha = b.parse_current_roster(roster_raw)
    (RAW/f'fantacalcio-current-{roster_sha[:12]}.html').write_bytes(roster_raw)

    st, catalog_raw, err = b.request_bytes(b.BIWENGER_CATALOG_URL)
    if st != 200 or not catalog_raw:
        raise RuntimeError(f'Biwenger catalog failed {st} {err}')
    catalog_sha=b.sha256(catalog_raw); (RAW/f'biwenger-serie-a-{catalog_sha[:12]}.json').write_bytes(catalog_raw)
    payload=b.parse_json(catalog_raw); catalog=b.catalog_players(payload)
    raw_teams=((payload or {}).get('data') or {}).get('teams') or {}
    teams={int(k):v for k,v in raw_teams.items() if isinstance(v,dict)} if isinstance(raw_teams,dict) else {int(x['id']):x for x in raw_teams if isinstance(x,dict) and x.get('id') is not None}

    identities=[resolve(p,catalog,teams) for p in targets]
    # Preserve V1 exact multi-token resolutions even if provider team propagation lags.
    v1=[b.resolve_identity(p,catalog) for p in targets]
    v1map={r['playerId']:r for r in v1}
    final=[]
    for row in identities:
        old=v1map[row['playerId']]
        if old['identityStatus']=='RESOLVED_SAFE':
            final.append({**old,'identityStatus':'RESOLVED_SAFE_A2','identityMethod':'V1_EXACT_CURRENT_MULTI_TOKEN_NAME'})
        else:
            final.append(row)
    safe=[r for r in final if r['identityStatus']=='RESOLVED_SAFE_A2']

    metadata=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        metadata.extend(pool.map(b.fetch_metadata,[{**r,'identityStatus':'RESOLVED_SAFE'} for r in safe]))
    tasks,zero_games,unknown=b.build_tasks(metadata)
    if unknown:
        raise RuntimeError(f'unclassified competition slugs {dict(unknown)}')
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results.extend(pool.map(b.fetch_history,tasks))

    history=[]
    for res in results:
        if res.get('fetchStatus')!='OK' or not res.get('e2ePass'):
            continue
        for report in res.get('reports') or []:
            history.append({
                'nexusPlayerId':res['playerId'],'nexusName':res['name'],'classicRole':res['classicRole'],'birthday':res.get('birthday'),
                'season':{'id':res['seasonId'],'name':res['season']},
                'competition':{'id':res.get('competitionId'),'name':res.get('competitionName'),'slug':res['competitionSlug']},
                'historicalPlayerId':res.get('historicalPlayerId'),'playerSlug':res.get('playerSlug'),
                'source':{'url':res['url'],'sha256':res['sha256'],'provenance':'PUBLIC_RUNNER_NETWORK_POST_DEADLINE_29_A2'},
                'report':report,
            })
    unresolved=[r for r in final if r['identityStatus']!='RESOLVED_SAFE_A2']
    transport=[r for r in metadata if r.get('fetchStatus')!='OK']+[r for r in results if r.get('fetchStatus')!='OK' or not r.get('e2ePass')]
    all_minutes=all(isinstance(r['report'].get('rawStats'),dict) and 'minutesPlayed' in r['report']['rawStats'] for r in history)
    summary={
        'schema':'NEXUS_POST_DEADLINE_29_IDENTITY_REMEDIATION_A2_V1',
        'status':'PASS_A2_TYPED_RESIDUALS' if all_minutes and not transport else 'BLOCKED_A2_TRANSPORT_OR_SCHEMA',
        'authority':{'expectedTargets':29,'fantacalcioSelectedTargets':len(targets),'fantacalcioRawSha256':roster_sha,'biwengerCatalogSha256':catalog_sha},
        'identityCounts':dict(sorted(Counter(r['identityStatus'] for r in final).items())),
        'resolvedSafeA2':len(safe),'unresolvedA2':len(unresolved),
        'metadataOk':sum(r.get('fetchStatus')=='OK' for r in metadata),'historyTasks':len(tasks),'historyTaskPass':sum(r.get('fetchStatus')=='OK' and r.get('e2ePass') for r in results),
        'zeroGameReferencesNotSynthesized':zero_games,'historyRows':len(history),'playersWithPositiveHistory':len({r['nexusPlayerId'] for r in history}),
        'transportOrSchemaGaps':len(transport),'allHistoryRowsHaveMinutesPlayed':all_minutes,
        'scientificBoundary':{
            'currentTeamUsedOnlyForIdentityCorroboration':True,'predictionValuesUsedForIdentityMatching':False,
            'fuzzySimilarityUsed':False,'manualPlayerOverrideUsed':False,'modelFitPerformed':False,'trainingDataModified':False,
            'predictiveEngineModified':False,'featurePromotionAllowed':False,'decisionLayerModified':False,'currentPredictionsMutated':False,
        },
        'nextGate':'RESOLVE_ONLY_REMAINING_A2_IDENTITIES_WITH POSITIVE_PROFILE_OR_HISTORICAL_PROVIDER_EVIDENCE; DO_NOT FALL BACK TO GENERIC TEMPLATES',
    }
    for name,obj in [('summary.json',summary),('identity-a2.json',final),('unresolved-a2.json',unresolved),('metadata-a2.json',metadata),('fetch-results-a2.json',results),('history-rows-a2.json',history),('transport-gaps-a2.json',transport)]:
        (OUT/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))
    if transport:
        raise RuntimeError('A2 transport/schema gaps present')

if __name__=='__main__':
    main()
