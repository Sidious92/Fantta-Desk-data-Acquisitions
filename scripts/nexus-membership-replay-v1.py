from __future__ import annotations

import base64, csv, hashlib, json, lzma
from collections import defaultdict
from pathlib import Path

ROOT = Path('data/nexus/membership-replay/v1')
PARTS = [ROOT / f'membership-replay-mirror-v1.part0{i}.b64' for i in range(1,5)]
OUT = Path('/tmp/nexus-membership-replay-v1')
OUT.mkdir(parents=True, exist_ok=True)
XZ_SHA = 'f5c7c6640cfc146b6dd8951ba04dea4082c7dbe9d2940da442d7d2673a0d108a'
RAW_SHA = '9a27966a07cd18a1966b8c86100bf468fbad3c07e3ec981af23b807f4bb3eec1'
NEW = 'NEWCOMER_CLUB_SEASON_TRANSITION'
CONT = 'NOT_NEWCOMER_AT_SEASON_BOUNDARY'


def mean(xs): return sum(xs)/len(xs)
def mae(rows, field): return mean([abs(float(r[field])-float(r['actual'])) for r in rows])

def tables(rows):
    c, cr = defaultdict(list), defaultdict(list)
    for r in rows:
        v=float(r['residualAfterA1']); cls=r['membershipClass']; role=r['role']
        c[cls].append(v); cr[(cls,role)].append(v)
    return c, cr

def corr(cls, role, t):
    c,cr=t
    vals = cr.get((cls,role), [])
    level='MEMBERSHIP_CLASS_ROLE'
    if len(vals)<8:
        vals=c.get(cls, []); level='MEMBERSHIP_CLASS'
    if len(vals)<8: return 0.0,'ZERO_INSUFFICIENT_SUPPORT',0
    n=len(vals); m=mean(vals)
    return max(-900.0,min(900.0,n*m/(n+20.0))),level,n

def main():
    encoded=''.join(p.read_text().strip() for p in PARTS)
    assert len(encoded)==16892, len(encoded)
    xz=base64.b64decode(encoded)
    actual_xz_sha=hashlib.sha256(xz).hexdigest()
    assert actual_xz_sha==XZ_SHA, (actual_xz_sha,XZ_SHA)
    raw=lzma.decompress(xz)
    actual_raw_sha=hashlib.sha256(raw).hexdigest()
    assert actual_raw_sha==RAW_SHA, (actual_raw_sha, RAW_SHA)
    rows=list(csv.DictReader(raw.decode().splitlines()))
    by={s:[r for r in rows if r['season']==s] for s in ('2023-24','2024-25','2025-26')}
    assert {k:len(v) for k,v in by.items()}=={'2023-24':162,'2024-25':85,'2025-26':120}

    eval_rows=[]; by_season={}
    for season,priors in [('2024-25',['2023-24']),('2025-26',['2023-24','2024-25'])]:
        t=tables([r for p in priors for r in by[p]])
        out=[]
        for r in by[season]:
            d,level,n=corr(r['membershipClass'],r['role'],t)
            z=dict(r); z['membershipCorrection']=d; z['correctionLevel']=level; z['correctionGroupN']=n
            z['combinedAdjusted']=max(0.0,min(3420.0,float(r['a1Adjusted'])+d)); out.append(z)
        eval_rows += out
        by_season[season]={'rows':len(out),'coreMae':mae(out,'a7Core'),'a1Mae':mae(out,'a1Adjusted'),'combinedMae':mae(out,'combinedAdjusted')}

    new=[r for r in eval_rows if r['membershipClass']==NEW]
    cont=[r for r in eval_rows if r['membershipClass']==CONT]
    overall={'rows':len(eval_rows),'coreMae':mae(eval_rows,'a7Core'),'a1Mae':mae(eval_rows,'a1Adjusted'),'combinedMae':mae(eval_rows,'combinedAdjusted')}
    sub={'newcomer':{'rows':len(new),'a1Mae':mae(new,'a1Adjusted'),'combinedMae':mae(new,'combinedAdjusted')},
         'continuity':{'rows':len(cont),'a1Mae':mae(cont,'a1Adjusted'),'combinedMae':mae(cont,'combinedAdjusted')}}
    gates={'overallImprovesVsA1':overall['combinedMae']<overall['a1Mae'],
           'newcomerNotWorse':sub['newcomer']['combinedMae']<=sub['newcomer']['a1Mae'],
           'continuityNotWorse':sub['continuity']['combinedMae']<=sub['continuity']['a1Mae'],
           'bothSeasonsNotWorse':all(v['combinedMae']<=v['a1Mae'] for v in by_season.values())}
    accepted=all(gates.values())
    summary={'schema':'NEXUS_MEMBERSHIP_REPLAY_V1','status':'PASS_MEMBERSHIP_INCREMENT' if accepted else 'REJECT_MEMBERSHIP_INCREMENT_KEEP_A7_A1',
      'mirror':{'rows':len(rows),'seedRows':162,'developmentRows':205,'rawSha256':actual_raw_sha,'xzSha256':actual_xz_sha,
                'joinNote':'Exact same-season normalized playerNameCandidate + targetClubCode mapping; only rows with frozen verified F3 target labels retained.'},
      'development':{'overall':overall,'bySeason':by_season,'deltaVsA1':overall['combinedMae']-overall['a1Mae']},
      'subgroups':sub,'gates':gates,
      'scientificBoundary':{'current2026_27OutcomesUsed':False,'servingMutated':False,'predictiveEngineModified':False,'trainingModified':False,'decisionLayerModified':False}}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    with (OUT/'development-rows.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=eval_rows[0].keys()); w.writeheader(); w.writerows(eval_rows)
    print(json.dumps(summary,indent=2,sort_keys=True))

if __name__=='__main__': main()
