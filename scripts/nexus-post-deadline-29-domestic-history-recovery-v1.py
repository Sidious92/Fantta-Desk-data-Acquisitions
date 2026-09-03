from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

OUT = Path('/tmp/nexus-post-deadline-29-domestic-history-recovery-v1')
RAW = OUT / 'raw'
OUT.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)

FANTACALCIO_URL = 'https://www.fantacalcio.it/quotazioni-fantacalcio'
BIWENGER_CATALOG_URL = 'https://cf.biwenger.com/api/v2/competitions/serie-a/data?lang=es'
PLAYER_FIELDS = '*,team,seasons,competition'
REPORT_FIELDS = '*,reports,competition,seasons'
USER_AGENT = 'FantaNexus-PostDeadline29-Recovery/1.0'

TARGET_IDS = {
    256, 795, 801, 2874, 4137, 4147, 5336, 5680, 5694, 5742,
    5751, 6344, 6537, 6752, 6826, 6833, 7092, 7220, 7232, 7579,
    7618, 7619, 7620, 7621, 7622, 7623, 7624, 7625, 7626,
}
TARGET_SEASONS = {2024: '2023-24', 2025: '2024-25', 2026: '2025-26'}
ADMITTED = {'serie-a', 'la-liga', 'ligue-1', 'premier-league', 'primeira-liga', 'segunda-division'}
EXCLUDED = {'champions-league', 'club-world-cup', 'copa-america', 'copa-del-rey', 'euro', 'supercopa', 'supercup', 'world-cup'}
TEAM_BY_SLUG = {
    'atalanta':'Atalanta','bologna':'Bologna','cagliari':'Cagliari','como':'Como','fiorentina':'Fiorentina',
    'frosinone':'Frosinone','genoa':'Genoa','inter':'Inter','juventus':'Juventus','lazio':'Lazio','lecce':'Lecce',
    'milan':'Milan','monza':'Monza','napoli':'Napoli','parma':'Parma','roma':'Roma','sassuolo':'Sassuolo',
    'torino':'Torino','udinese':'Udinese','venezia':'Venezia',
}


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def norm(value: Any) -> str:
    text = unicodedata.normalize('NFKD', str(value or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).lower()
    text = text.replace("'", ' ').replace('’', ' ')
    return ' '.join(re.findall(r'[a-z0-9]+', text))


def request_bytes(url: str, attempts: int = 8) -> tuple[int | None, bytes, str | None]:
    last = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers={
                'User-Agent': USER_AGENT,
                'Accept': 'application/json,text/html,*/*;q=0.8',
                'Referer': 'https://biwenger.as.com/players',
            })
            with urllib.request.urlopen(req, timeout=45) as response:
                return int(response.status), response.read(), None
        except urllib.error.HTTPError as exc:
            body = exc.read()
            if exc.code == 429 and attempt + 1 < attempts:
                last = f'HTTP_429:{body[:120]!r}'
                time.sleep(min(20.0, 2.0 + attempt * 2.5))
                continue
            return int(exc.code), body, f'HTTP_{exc.code}'
        except Exception as exc:  # noqa: BLE001
            last = repr(exc)
            if attempt + 1 < attempts:
                time.sleep(min(10.0, 1.0 + attempt * 1.5))
                continue
    return None, b'', last or 'UNKNOWN_TRANSPORT_ERROR'


def parse_json(raw: bytes) -> Any:
    text = raw.decode('utf-8', 'replace').strip()
    text = re.sub(r'^jsonp_\d+\(', '', text)
    text = re.sub(r'\);?\s*$', '', text)
    return json.loads(text)


def parse_current_roster(raw: bytes) -> tuple[list[dict[str, Any]], str]:
    html = raw.decode('utf-8', 'replace')
    soup = BeautifulSoup(html, 'html.parser')
    rows = soup.select('tr.player-row')
    players = []
    for row in rows:
        anchor = row.select_one('a.player-link[href],a.player-name[href],a[href*="/serie-a/squadre/"]')
        if not anchor:
            continue
        href = anchor.get('href') or ''
        match = re.search(r'/serie-a/squadre/([^/]+)/[^/]+/(\d+)/?$', href)
        if not match:
            continue
        slug, pid_raw = match.groups()
        club = TEAM_BY_SLUG.get(slug.lower())
        role = str(row.get('data-filter-role-classic') or '').strip().upper()
        name = ' '.join(anchor.get_text(' ', strip=True).split())
        if club and role in {'P','D','C','A'} and name:
            players.append({'playerId': int(pid_raw), 'name': name, 'club': club, 'classicRole': role})
    ids = [p['playerId'] for p in players]
    if not players or len(ids) != len(set(ids)):
        raise RuntimeError(f'Fantacalcio live roster parse invalid rows={len(players)} unique={len(set(ids))}')
    selected = [p for p in players if p['playerId'] in TARGET_IDS]
    missing = sorted(TARGET_IDS - {p['playerId'] for p in selected})
    if missing:
        raise RuntimeError(f'canonical 29 ids missing from live roster: {missing}')
    if len(selected) != 29:
        raise RuntimeError(f'target selected cardinality drift: {len(selected)}')
    return sorted(selected, key=lambda x: x['playerId']), sha256(raw)


def catalog_players(payload: Any) -> list[dict[str, Any]]:
    players = ((payload or {}).get('data') or {}).get('players')
    if isinstance(players, dict):
        return [dict(v) for v in players.values() if isinstance(v, dict)]
    if isinstance(players, list):
        return [dict(v) for v in players if isinstance(v, dict)]
    raise RuntimeError('Biwenger catalog data.players missing')


def player_names(row: dict[str, Any]) -> set[str]:
    vals = []
    for key in ('name','fullName','displayName','slug'):
        if row.get(key):
            vals.append(str(row[key]).replace('-', ' '))
    return {norm(v) for v in vals if norm(v)}


def resolve_identity(player: dict[str, Any], catalog: list[dict[str, Any]]) -> dict[str, Any]:
    current = norm(player['name'])
    exact = []
    weak = []
    for row in catalog:
        names = player_names(row)
        if not names:
            continue
        if len(current.split()) >= 2 and current in names:
            exact.append(row)
        elif current and any(current == n or current in n.split() for n in names):
            weak.append(row)
    if len(exact) == 1:
        row = exact[0]
        return {**player, 'identityStatus':'RESOLVED_SAFE', 'identityMethod':'EXACT_CURRENT_MULTI_TOKEN_NAME',
                'providerId':row.get('id'),'providerName':row.get('name'),'providerSlug':row.get('slug'),
                'candidateCount':1}
    if len(exact) > 1:
        return {**player, 'identityStatus':'AMBIGUOUS_SAFE_EVIDENCE','identityMethod':None,
                'providerId':None,'providerName':None,'providerSlug':None,'candidateCount':len(exact)}
    if len(weak) == 1:
        row = weak[0]
        return {**player, 'identityStatus':'REVIEW_ONLY_SINGLE_TOKEN','identityMethod':'SINGLE_TOKEN_REVIEW_ONLY',
                'providerId':row.get('id'),'providerName':row.get('name'),'providerSlug':row.get('slug'),'candidateCount':1}
    return {**player, 'identityStatus':'NO_SAFE_CATALOG_MATCH','identityMethod':None,
            'providerId':None,'providerName':None,'providerSlug':None,'candidateCount':len(weak)}


def metadata_url(slug: str) -> str:
    q = urllib.parse.urlencode({'fields':PLAYER_FIELDS,'lang':'es'}, safe='*,()')
    return f'https://cf.biwenger.com/api/v2/players/serie-a/{urllib.parse.quote(slug)}?{q}'


def season_refs(payload: Any) -> list[dict[str, Any]]:
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return []
    refs = data.get('seasons')
    if isinstance(refs, list):
        return [r for r in refs if isinstance(r, dict)]
    if isinstance(refs, dict):
        return [r for r in refs.values() if isinstance(r, dict)]
    return []


def fetch_metadata(row: dict[str, Any]) -> dict[str, Any]:
    slug = row.get('providerSlug')
    if not slug:
        return {**row,'fetchStatus':'NO_SLUG','seasonReferences':[]}
    url = metadata_url(str(slug))
    status, raw, error = request_bytes(url)
    if status != 200 or not raw:
        return {**row,'fetchStatus':'ERROR','httpStatus':status,'error':error,'url':url,'seasonReferences':[]}
    payload = parse_json(raw)
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {**row,'fetchStatus':'SCHEMA_FAIL','httpStatus':status,'url':url,'seasonReferences':[]}
    response_id = data.get('id')
    response_slug = data.get('slug')
    if int(response_id) != int(row['providerId']) or str(response_slug) != str(slug):
        return {**row,'fetchStatus':'IDENTITY_MISMATCH','httpStatus':status,'url':url,'seasonReferences':[]}
    digest = sha256(raw)
    (RAW/f'metadata-{row["playerId"]}-{digest[:12]}.json').write_bytes(raw)
    return {**row,'fetchStatus':'OK','httpStatus':200,'url':url,'sha256':digest,
            'birthday':data.get('birthday'),'seasonReferences':season_refs(payload)}


def locator(meta: dict[str, Any], ref: dict[str, Any]) -> dict[str, Any]:
    comp = ref.get('competition') if isinstance(ref.get('competition'), dict) else None
    player = ref.get('player') if isinstance(ref.get('player'), dict) else None
    if bool(comp) != bool(player):
        return {'kind':'MALFORMED'}
    if comp and player:
        return {'kind':'EXPLICIT','competitionSlug':comp.get('slug'),'competitionId':comp.get('id'),
                'competitionName':comp.get('name'),'playerSlug':player.get('slug'),'historicalPlayerId':player.get('id')}
    return {'kind':'IMPLICIT_CURRENT','competitionSlug':'serie-a','competitionId':5,'competitionName':'Serie A',
            'playerSlug':meta.get('providerSlug'),'historicalPlayerId':meta.get('providerId')}


def build_tasks(metadata: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, Counter]:
    tasks=[]; zero_games=0; unknown=Counter()
    for row in metadata:
        if row.get('fetchStatus') != 'OK':
            continue
        for ref in row.get('seasonReferences') or []:
            sid = ref.get('id')
            try: sid = int(sid)
            except (TypeError,ValueError): continue
            if sid not in TARGET_SEASONS or ref.get('selected'):
                continue
            loc = locator(row, ref)
            if loc['kind']=='MALFORMED':
                raise RuntimeError(f'malformed season reference player={row["playerId"]}')
            comp = str(loc.get('competitionSlug'))
            if comp in EXCLUDED:
                continue
            if comp not in ADMITTED:
                unknown[comp]+=1; continue
            games = int(ref.get('games') or 0)
            if games <= 0:
                zero_games += 1; continue
            if not loc.get('playerSlug'):
                raise RuntimeError(f'missing historical slug player={row["playerId"]}')
            tasks.append({
                'playerId':row['playerId'],'name':row['name'],'club':row['club'],'classicRole':row['classicRole'],
                'birthday':row.get('birthday'),'seasonId':sid,'season':TARGET_SEASONS[sid],'games':games,
                **loc,
            })
    keys=[(t['playerId'],t['competitionSlug'],t['seasonId']) for t in tasks]
    if len(keys)!=len(set(keys)):
        raise RuntimeError('duplicate history task key')
    return tasks, zero_games, unknown


def history_url(task: dict[str, Any]) -> str:
    q=urllib.parse.urlencode({'lang':'es','season':str(task['seasonId']),'fields':REPORT_FIELDS}, safe='*,()')
    return f'https://cf.biwenger.com/api/v2/players/{urllib.parse.quote(str(task["competitionSlug"]))}/{urllib.parse.quote(str(task["playerSlug"]))}?{q}'


def object_rows(v: Any) -> list[dict[str, Any]]:
    if isinstance(v,list): return [x for x in v if isinstance(x,dict)]
    if isinstance(v,dict): return [x for x in v.values() if isinstance(x,dict)]
    return []


def fetch_history(task: dict[str, Any]) -> dict[str, Any]:
    url=history_url(task)
    status,raw,error=request_bytes(url)
    if status!=200 or not raw:
        return {**task,'fetchStatus':'ERROR','httpStatus':status,'error':error,'url':url,'reports':[],'e2ePass':False}
    payload=parse_json(raw); data=payload.get('data') if isinstance(payload,dict) else None
    if not isinstance(data,dict):
        return {**task,'fetchStatus':'SCHEMA_FAIL','httpStatus':status,'url':url,'reports':[],'e2ePass':False}
    reports=object_rows(data.get('reports')); raw_reports=[r for r in reports if isinstance(r.get('rawStats'),dict)]
    comp=data.get('competition') if isinstance(data.get('competition'),dict) else {}
    seasons=object_rows(data.get('seasons')); selected=[]
    for s in seasons:
        if s.get('selected'):
            try: selected.append(int(s.get('id')))
            except (TypeError,ValueError): pass
    slug_ok=data.get('slug')==task['playerSlug']; comp_ok=(not comp or comp.get('slug')==task['competitionSlug'])
    season_ok=(not selected or task['seasonId'] in selected); games_ok=len(raw_reports)==int(task['games'])
    e2e=bool(slug_ok and comp_ok and season_ok and games_ok)
    digest=sha256(raw); (RAW/f'history-{task["playerId"]}-{task["competitionSlug"]}-{task["seasonId"]}-{digest[:12]}.json').write_bytes(raw)
    return {**task,'fetchStatus':'OK' if e2e else 'SCHEMA_FAIL','httpStatus':200,'url':url,'sha256':digest,
            'e2ePass':e2e,'reportRows':len(raw_reports),'reports':raw_reports}


def main() -> None:
    status, roster_raw, error = request_bytes(FANTACALCIO_URL)
    if status != 200 or not roster_raw:
        raise RuntimeError(f'Fantacalcio fetch failed status={status} error={error}')
    targets, roster_sha = parse_current_roster(roster_raw)
    (RAW/f'fantacalcio-current-{roster_sha[:12]}.html').write_bytes(roster_raw)

    status, catalog_raw, error = request_bytes(BIWENGER_CATALOG_URL)
    if status != 200 or not catalog_raw:
        raise RuntimeError(f'Biwenger catalog failed status={status} error={error}')
    catalog_sha=sha256(catalog_raw); (RAW/f'biwenger-serie-a-{catalog_sha[:12]}.json').write_bytes(catalog_raw)
    catalog=catalog_players(parse_json(catalog_raw))
    if len(catalog)<300:
        raise RuntimeError(f'Biwenger catalog unexpectedly small {len(catalog)}')

    identities=[resolve_identity(p,catalog) for p in targets]
    safe=[r for r in identities if r['identityStatus']=='RESOLVED_SAFE']
    metadata=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        metadata.extend(pool.map(fetch_metadata,safe))
    tasks,zero_games,unknown=build_tasks(metadata)
    if unknown:
        raise RuntimeError(f'unclassified competition slugs: {dict(unknown)}')
    results=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results.extend(pool.map(fetch_history,tasks))
    time.sleep(0.1)

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
                'source':{'url':res['url'],'sha256':res['sha256'],'provenance':'PUBLIC_RUNNER_NETWORK_POST_DEADLINE_29'},
                'report':report,
            })
    gaps=[r for r in identities if r['identityStatus']!='RESOLVED_SAFE'] + [r for r in metadata if r.get('fetchStatus')!='OK'] + [r for r in results if r.get('fetchStatus')!='OK' or not r.get('e2ePass')]
    all_minutes=all(isinstance(r['report'].get('rawStats'),dict) and 'minutesPlayed' in r['report']['rawStats'] for r in history)
    summary={
        'schema':'NEXUS_POST_DEADLINE_29_DOMESTIC_HISTORY_RECOVERY_V1',
        'status':'PASS_TARGETED_RECOVERY_WITH_TYPED_IDENTITY_GAPS' if all_minutes else 'BLOCKED_HISTORY_SCHEMA_GAP',
        'authority':{
            'canonicalAddedActiveIds':sorted(TARGET_IDS),'expectedTargets':29,'fantacalcioSelectedTargets':len(targets),
            'fantacalcioRawSha256':roster_sha,'biwengerCatalogSha256':catalog_sha,
        },
        'identityCounts':dict(sorted(Counter(r['identityStatus'] for r in identities).items())),
        'safeResolved':len(safe),'metadataOk':sum(r.get('fetchStatus')=='OK' for r in metadata),
        'historyTasks':len(tasks),'zeroGameReferencesNotSynthesized':zero_games,
        'historyTaskPass':sum(r.get('fetchStatus')=='OK' and r.get('e2ePass') for r in results),
        'historyRows':len(history),'playersWithPositiveHistory':len({r['nexusPlayerId'] for r in history}),
        'typedGapRows':len(gaps),'allHistoryRowsHaveMinutesPlayed':all_minutes,
        'scientificBoundary':{
            'predictionValuesUsedForIdentityMatching':False,'fuzzyIdentityAutoAccepted':False,'singleTokenAutoAccepted':False,
            'modelFitPerformed':False,'trainingDataModified':False,'predictiveEngineModified':False,
            'featurePromotionAllowed':False,'decisionLayerModified':False,'currentPredictionsMutated':False,
        },
        'nextGate':'RESOLVE_ONLY_TYPED_IDENTITY_GAPS_THEN_MERGE_WITH_FROZEN_A6_523_HISTORY_AND_REBUILD_532_SURFACE_USING_UNCHANGED_HURDLE_HGB_A7',
    }
    for name,obj in [('summary.json',summary),('targets.json',targets),('identity.json',identities),('metadata.json',metadata),('fetch-results.json',results),('history-rows.json',history),('typed-gaps.json',gaps)]:
        (OUT/name).write_text(json.dumps(obj,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))


if __name__=='__main__':
    main()
