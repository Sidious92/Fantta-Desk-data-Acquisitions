#!/usr/bin/env python3
import argparse, gzip, hashlib, json, re, time, urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

D1_COMMIT='d0cab101cc90f65ee0b1982e7ca974cd95c5d3b9'
D1_SHA256='952bdf1d4cfb81a0683bff1f78d949b6350b11be1cc27d20059f7ace651bb53c'
D1_URL=f'https://raw.githubusercontent.com/Sidious92/Fantta-Desk-data-Acquisitions/{D1_COMMIT}/data/nexus-d1/final-v3/IDENTITY_MASTER.json'
TARGET_PATH=Path('data/nexus-f2/targets/f2b-2025-26-understat-targets-v1.json')
API='https://understat.com/getPlayerData/{player_id}'
UA='Mozilla/5.0 (compatible; FantaNexus-F2-2025-Label-Extension/1.0)'
TARGET_SEASON='2025/26'
TARGET_PROVIDER_SEASON='2025'
FIELDS=['games','time','goals','npg','assists','shots','key_passes']
EXPECTED=['xG','npxG','xA','xGChain','xGBuildup']

def H(b): return hashlib.sha256(b).hexdigest()

def fetch(url, ajax=False):
    headers={'User-Agent':UA,'Accept':'application/json,text/plain,*/*','Accept-Encoding':'gzip'}
    if ajax: headers['X-Requested-With']='XMLHttpRequest'
    req=urllib.request.Request(url,headers=headers)
    with urllib.request.urlopen(req,timeout=90) as r:
        wire=r.read(); enc=str(r.headers.get('Content-Encoding') or '').lower()
        if r.status!=200: raise RuntimeError(f'HTTP_{r.status}:{url}')
        raw=gzip.decompress(wire) if wire.startswith(b'\x1f\x8b') or 'gzip' in enc else wire
        return wire,raw,enc

def season(v):
    s=str(v or '').strip()
    if s==TARGET_PROVIDER_SEASON: return TARGET_SEASON
    m=re.fullmatch(r'(\d{4})/(\d{2})',s)
    if m and int(m.group(2))==(int(m.group(1))+1)%100: return s
    if re.fullmatch(r'\d{4}',s):
        y=int(s); return f'{y}/{(y+1)%100:02d}'
    raise ValueError(s)

def iv(v,field,pid):
    f=float(v or 0); i=int(f)
    if f!=i: raise RuntimeError(f'NON_INTEGER:{pid}:{field}:{v!r}')
    return i

def write_json(path,obj):
    raw=(json.dumps(obj,ensure_ascii=False,indent=2,sort_keys=True)+'\n').encode(); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(raw); return {'path':str(path),'bytes':len(raw),'sha256':H(raw)}

def write_jsonl(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8',newline='\n') as f:
        for r in rows: f.write(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n')
    raw=path.read_bytes(); return {'path':str(path),'bytes':len(raw),'rows':len(rows),'sha256':H(raw)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--shard-index',type=int,required=True); ap.add_argument('--shard-count',type=int,required=True); ap.add_argument('--delay',type=float,default=0.35); args=ap.parse_args()
    out=Path(f'.nexus-f2b-2025-label-extension-v1/shard-{args.shard_index:02d}'); rawdir=out/'raw'; rawdir.mkdir(parents=True,exist_ok=True)
    target_raw=TARGET_PATH.read_bytes(); target=json.loads(target_raw); ids=[str(x) for x in target['understatPlayerIds']]
    if target.get('count')!=451 or len(ids)!=451 or len(set(ids))!=451 or target.get('season')!=TARGET_SEASON: raise SystemExit('TARGET_LIST_INVALID')
    d1_wire,d1_raw,_=fetch(D1_URL)
    if H(d1_raw)!=D1_SHA256: raise SystemExit('D1_HASH_MISMATCH')
    d1=json.loads(d1_raw); alias_to_person={}
    for p in d1.get('persons',[]):
        if not p.get('globalPersonPromotionGranted'): continue
        for a in p.get('providerAliases',[]):
            if a.get('provider')=='Understat' and a.get('providerId') is not None: alias_to_person[str(a['providerId'])]=p['personKey']
    missing=[pid for pid in ids if pid not in alias_to_person]
    if missing: raise SystemExit(f'TARGET_D1_ALIAS_MISSING:{missing[:10]}')
    shard_ids=[pid for i,pid in enumerate(ids) if i%args.shard_count==args.shard_index]
    labels=[]; duplicates=[]; qa=[]; index=[]; failures=[]
    for pos,pid in enumerate(shard_ids):
        if pos: time.sleep(args.delay)
        try:
            wire,decoded,encoding=fetch(API.format(player_id=pid),ajax=True); payload=json.loads(decoded.decode('utf-8'))
            matches=payload.get('matches') if isinstance(payload,dict) else None
            if not isinstance(matches,list): raise RuntimeError('INVALID_API_SHAPE')
        except Exception as exc:
            failures.append({'code':'PLAYER_REQUEST_OR_PARSE_FAILED','playerId':pid,'error':repr(exc)}); continue
        (rawdir/f'player-{pid}-wire.bin').write_bytes(wire); (rawdir/f'player-{pid}-api.json').write_bytes(decoded)
        target_matches=[]
        for m in matches:
            try: sea=season(m.get('season'))
            except Exception: continue
            if sea!=TARGET_SEASON: continue
            mid=str(m.get('id') or '')
            date=str(m.get('date') or '').split()[0]
            if not mid: failures.append({'code':'MATCH_ID_MISSING','playerId':pid}); continue
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date): failures.append({'code':'MATCH_DATE_INVALID','playerId':pid,'matchId':mid,'date':m.get('date')}); continue
            try: datetime.strptime(date,'%Y-%m-%d')
            except Exception: failures.append({'code':'MATCH_DATE_INVALID','playerId':pid,'matchId':mid,'date':m.get('date')}); continue
            obs={f:iv(m.get(f,0),f,pid) for f in FIELDS if f!='games'}; obs['games']=1
            target_matches.append({'matchId':mid,'date':date,'hTeam':str(m.get('h_team') or ''),'aTeam':str(m.get('a_team') or ''),'observations':obs})
        by_mid=defaultdict(list)
        for m in target_matches: by_mid[m['matchId']].append(m)
        events=[]; duplicate_contrib={f:0 for f in FIELDS}; hard_duplicate=False
        for mid,group in sorted(by_mid.items(),key=lambda kv:(kv[0].isdigit()==False,int(kv[0]) if kv[0].isdigit() else kv[0])):
            first=group[0]; sig=(first['date'],first['hTeam'],first['aTeam'],tuple(first['observations'][f] for f in FIELDS))
            if len(group)>1:
                same=all((x['date'],x['hTeam'],x['aTeam'],tuple(x['observations'][f] for f in FIELDS))==sig for x in group[1:])
                duplicates.append({'playerId':pid,'personKey':alias_to_person[pid],'matchId':mid,'rawRows':len(group),'observedIdentical':same,'keptFootballEvents':1 if same else 0})
                if not same:
                    failures.append({'code':'DUPLICATE_MATCH_OBSERVED_CONFLICT','playerId':pid,'matchId':mid,'rawRows':len(group)}); hard_duplicate=True; continue
                for _ in group[1:]:
                    for f in FIELDS: duplicate_contrib[f]+=first['observations'][f]
            events.append(first)
        sums={f:0 for f in FIELDS}; sums['games']=len(events)
        for e in events:
            for f in FIELDS:
                if f!='games': sums[f]+=e['observations'][f]
        group_rows=[]
        groups=payload.get('groups') if isinstance(payload,dict) else None
        if isinstance(groups,dict) and isinstance(groups.get('season'),list):
            group_rows=[g for g in groups['season'] if str(g.get('season'))==TARGET_PROVIDER_SEASON]
        gsums={f:0 for f in FIELDS}
        for g in group_rows:
            for f in FIELDS: gsums[f]+=iv(g.get(f,0),f,pid)
        group_status='NO_GROUP_REFERENCE'
        if group_rows:
            if gsums==sums: group_status='EXACT'
            elif all(gsums[f]==sums[f]+duplicate_contrib[f] for f in FIELDS) and any(duplicate_contrib.values()): group_status='EXPLAINED_TECHNICAL_DUPLICATE_CONTAMINATION'
            else: group_status='UNEXPLAINED_MISMATCH'
        released=(not hard_duplicate and group_status!='UNEXPLAINED_MISMATCH' and sums['time']>0)
        missing_reason=None if released else ('NO_POSITIVE_EXPOSURE' if sums['time']<=0 and not hard_duplicate else ('GROUPS_MISMATCH' if group_status=='UNEXPLAINED_MISMATCH' else 'DUPLICATE_OBSERVED_CONFLICT'))
        labels.append({'playerId':pid,'personKey':alias_to_person[pid],'season':TARGET_SEASON,'status':'OBSERVED' if released else 'MISSING','missingReason':missing_reason,'observations':sums if released else None,'eventCount':len(events),'rawTargetMatchRows':len(target_matches),'groupsQaStatus':group_status})
        qa.append({'playerId':pid,'personKey':alias_to_person[pid],'season':TARGET_SEASON,'eventSums':sums,'groupsSums':gsums if group_rows else None,'groupsRows':len(group_rows),'groupsQaStatus':group_status,'duplicateContribution':duplicate_contrib})
        index.append({'playerId':pid,'personKey':alias_to_person[pid],'wireBytes':len(wire),'wireSha256':H(wire),'decodedBytes':len(decoded),'decodedSha256':H(decoded),'contentEncoding':encoding,'providerMatchRows':len(matches),'targetRawMatchRows':len(target_matches),'targetFootballEvents':len(events)})
    observed=sum(1 for x in labels if x['status']=='OBSERVED'); missing_labels=sum(1 for x in labels if x['status']=='MISSING')
    hard_fail=len(failures)>0 or len(index)!=len(shard_ids) or len(labels)!=len(shard_ids)
    status='PASS' if not hard_fail else 'FAIL'
    files={'labels':write_jsonl(out/'labels.jsonl',labels),'duplicates':write_jsonl(out/'duplicates.jsonl',duplicates),'qa':write_jsonl(out/'qa.jsonl',qa),'playerIndex':write_json(out/'player-index.json',index)}
    reg={'schema':'NEXUS_F2B_2025_26_EVENT_LABEL_EXTENSION_SHARD_V1','status':status,'capturedAt':datetime.now(timezone.utc).isoformat(),'shardIndex':args.shard_index,'shardCount':args.shard_count,'targetList':{'path':str(TARGET_PATH),'sha256':H(target_raw),'count':len(ids)},'d1':{'commit':D1_COMMIT,'sha256':D1_SHA256},'counts':{'playersExpected':len(shard_ids),'playersFetched':len(index),'labels':len(labels),'observedLabels':observed,'missingLabels':missing_labels,'duplicateTechnicalGroups':len(duplicates),'failures':len(failures)},'files':files,'failures':failures,'governance':{'expectedFieldsPreservedRawOnly':EXPECTED,'expectedFieldsReleased':False,'fuzzyMatchingUsed':False,'canonicalPredictiveEngineModified':False}}
    write_json(out/'SHARD_REGISTRY.json',reg); print(json.dumps({'status':status,'shard':args.shard_index,'expected':len(shard_ids),'fetched':len(index),'observed':observed,'missing':missing_labels,'duplicates':len(duplicates),'failures':len(failures)},indent=2))
    if status!='PASS': raise SystemExit(2)

if __name__=='__main__': main()
