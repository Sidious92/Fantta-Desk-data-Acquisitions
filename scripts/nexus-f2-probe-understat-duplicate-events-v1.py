#!/usr/bin/env python3
import argparse,gzip,hashlib,json,urllib.request
from pathlib import Path
from datetime import datetime,timezone

MATCHES={
 '23028':['2437','10561'],
 '29482':['11383','12322'],
}
IDENTITY=['id','season','date','h_team','a_team']
OBS=['time','goals','npg','assists','shots','key_passes']
ROSTER_OBS=['time','goals','assists','shots','key_passes']
ALLOWED_DIFF={'roster_id','xG','npxG','xA','xGChain','xGBuildup'}
API='https://understat.com/getMatchData/{mid}'
UA='Mozilla/5.0 (compatible; FantaNexus-F2-Duplicate-Event-Probe/1.0)'
SOURCE_PACKAGE_SHA='00a60a8a8b645e9bf171a354a4adb547c85b70085974596b093ea3dd7d5b329c'

def H(b): return hashlib.sha256(b).hexdigest()
def canon(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def fetch(mid):
 req=urllib.request.Request(API.format(mid=mid),headers={'User-Agent':UA,'Accept':'application/json','Accept-Encoding':'gzip','X-Requested-With':'XMLHttpRequest'})
 with urllib.request.urlopen(req,timeout=90) as r:
  wire=r.read(); enc=str(r.headers.get('Content-Encoding') or '').lower(); raw=gzip.decompress(wire) if wire.startswith(b'\x1f\x8b') or 'gzip' in enc else wire
  return wire,raw,enc

def find_player_file(root,pid):
 xs=list(root.rglob(f'player-{pid}-api.json'))
 if len(xs)!=1: raise RuntimeError(f'PLAYER_FILE_COUNT:{pid}:{len(xs)}')
 return xs[0]

def roster_rows(payload,pid):
 out=[]
 for side in ('h','a'):
  for row in (payload.get('rosters',{}).get(side,{}) or {}).values():
   if isinstance(row,dict) and str(row.get('player_id') or '')==pid: out.append((side,row))
 return out

def write(path,obj):
 raw=(json.dumps(obj,indent=2,sort_keys=True,ensure_ascii=False)+'\n').encode(); path.write_bytes(raw); return H(raw)

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--input-root',required=True); ap.add_argument('--output-root',required=True); args=ap.parse_args()
 root=Path(args.input_root); out=Path(args.output_root); out.mkdir(parents=True,exist_ok=True); rawdir=out/'raw'; rawdir.mkdir(exist_ok=True)
 failures=[]; evidence=[]
 for mid,pids in MATCHES.items():
  wire,raw,enc=fetch(mid); payload=json.loads(raw.decode()); (rawdir/f'match-{mid}-wire.bin').write_bytes(wire); (rawdir/f'match-{mid}-api.json').write_bytes(raw)
  for pid in pids:
   pdata=json.loads(find_player_file(root,pid).read_text()); rows=[m for m in pdata.get('matches',[]) if str(m.get('id') or '')==mid]
   if len(rows)!=2:
    failures.append({'code':'EXPECTED_DUPLICATE_PAIR_NOT_FOUND','playerId':pid,'matchId':mid,'rows':len(rows)}); continue
   allkeys=sorted(set().union(*(r.keys() for r in rows))); diffs=[k for k in allkeys if len({canon(r.get(k)) for r in rows})>1]
   ident=all(len({canon(r.get(k)) for r in rows})==1 for k in IDENTITY)
   observed=all(len({canon(r.get(k)) for r in rows})==1 for k in OBS)
   allowed=set(diffs).issubset(ALLOWED_DIFF)
   rr=roster_rows(payload,pid)
   roster_unique=len(rr)==1
   roster_match=False; side=None; roster_id=None
   roster_comp={}
   if roster_unique:
    side,rrow=rr[0]; roster_id=rrow.get('id')
    roster_comp={k:{'playerRow':str(rows[0].get(k)),'matchRoster':str(rrow.get(k)),'equal':str(rows[0].get(k))==str(rrow.get(k))} for k in ROSTER_OBS}
    roster_match=all(v['equal'] for v in roster_comp.values())
   rec={'playerId':pid,'matchId':mid,'duplicateRows':2,'identityEqual':ident,'releasedObservedEqual':observed,'differingFields':diffs,'differencesAllowedByObservedAmendment':allowed,'matchRosterPlayerRows':len(rr),'matchRosterUnique':roster_unique,'matchRosterSide':side,'matchRosterRowId':roster_id,'matchRosterObservedComparison':roster_comp,'matchRosterObservedExact':roster_match}
   evidence.append(rec)
   if not (ident and observed and allowed and roster_unique and roster_match): failures.append({'code':'DUPLICATE_EVENT_INDEPENDENT_VALIDATION_FAILED',**rec})
 status='PASS' if not failures else 'FAIL'
 report={'schema':'NEXUS_F2B_UNDERSTAT_DUPLICATE_EVENT_PROBE_V1','status':status,'capturedAt':datetime.now(timezone.utc).isoformat(),'sourcePackageSha256':SOURCE_PACKAGE_SHA,'providerEndpoint':'getMatchData/{match_id}','matchIds':sorted(MATCHES),'evidence':evidence,'failures':failures,'interpretation':{'onPass':'Each duplicated player-match pair is one provider match event: exact event identity and released observed fields agree across duplicate player rows, and getMatchData contains exactly one roster row for that player with matching observed match statistics. Aggregate/group double counting is therefore a source aggregate contamination for the released observed family, not evidence of two football events.','expectedFieldsRemainQuarantined':True,'rawRowsPreserved':True}}
 sha=write(out/'DUPLICATE_EVENT_PROBE.json',report)
 print(json.dumps({'status':status,'pairs':len(evidence),'failures':len(failures),'sha256':sha},indent=2))
 if status!='PASS': raise SystemExit(2)
if __name__=='__main__': main()
