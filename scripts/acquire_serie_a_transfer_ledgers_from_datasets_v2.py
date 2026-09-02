#!/usr/bin/env python3
import csv, gzip, hashlib, io, json, re, unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
import requests

SEASONS = [2022, 2023, 2024, 2025]
OUT = Path('artifacts/serie-a-five-season-transfer-ledgers-v2')
EORDO = 'https://raw.githubusercontent.com/eordo/transfermarkt-data/master/serie_a/{season}.csv'
DCARIBOU = 'https://pub-e682421888d945d684bcae8890b0ec20.r2.dev/data/transfers.csv.gz'
HEADERS = {'User-Agent':'Mozilla/5.0 FantaNexus scientific acquisition/1.0'}

def sha(b): return hashlib.sha256(b).hexdigest()
def norm(s):
    s=unicodedata.normalize('NFKD',s or '').encode('ascii','ignore').decode().lower()
    s=s.replace('&',' and ')
    s=re.sub(r'\b(fc|ac|calcio|cf|ssc|ss|us|as)\b',' ',s)
    return re.sub(r'[^a-z0-9]+',' ',s).strip()

def req(url):
    r=requests.get(url,headers=HEADERS,timeout=90)
    if r.status_code!=200: raise RuntimeError(f'HTTP {r.status_code}: {url}')
    return r.content

def season_labels(y):
    return {str(y),f'{y}/{str(y+1)[-2:]}',f'{str(y)[-2:]}/{str(y+1)[-2:]}',f'{y}-{y+1}',f'{str(y)[-2:]}-{str(y+1)[-2:]}'}

def date_window(date_s,y):
    try: d=datetime.strptime(date_s[:10],'%Y-%m-%d')
    except: return ''
    return 'winter' if d.year==y+1 and d.month<=4 else 'summer'

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    # Season club universes + independent team-side surface.
    eordo={}; clubmaps={}
    for y in SEASONS:
        b=req(EORDO.format(season=y)); rows=list(csv.DictReader(io.StringIO(b.decode('utf-8-sig'))))
        clubs=sorted({r['club'] for r in rows})
        if len(clubs)!=20: raise RuntimeError(f'{y}: eordo club universe {len(clubs)} != 20: {clubs}')
        eordo[y]=(b,rows,clubs)
        clubmaps[y]={norm(c):c for c in clubs}

    gz=req(DCARIBOU)
    raw=gzip.decompress(gz).decode('utf-8-sig')
    all_transfers=list(csv.DictReader(io.StringIO(raw)))
    manifests=[]

    for y in SEASONS:
        b, erows, clubs=eordo[y]; cmap=clubmaps[y]; labels=season_labels(y)
        # Discover actual season spelling in dcaribou while accepting stable variants.
        candidates=[]
        for r in all_transfers:
            ts=(r.get('transfer_season') or '').strip()
            if ts not in labels: continue
            fn,tn=norm(r.get('from_club_name')),norm(r.get('to_club_name'))
            if fn in cmap or tn in cmap:
                candidates.append(r)
        if not candidates:
            # Some releases use '2022/2023'.
            alt=f'{y}/{y+1}'
            for r in all_transfers:
                if (r.get('transfer_season') or '').strip()!=alt: continue
                fn,tn=norm(r.get('from_club_name')),norm(r.get('to_club_name'))
                if fn in cmap or tn in cmap: candidates.append(r)
        if not candidates: raise RuntimeError(f'{y}: no dcaribou candidate events')

        # Deduplicate native event records exactly by stable transfer coordinates.
        uniq={}
        for r in candidates:
            k=(r.get('player_id'),r.get('transfer_date'),norm(r.get('from_club_name')),norm(r.get('to_club_name')))
            uniq[k]=r
        events=[]
        for k,r in sorted(uniq.items(), key=lambda kv: ((kv[1].get('transfer_date') or ''),(kv[1].get('player_id') or ''))):
            fn,tn=norm(r.get('from_club_name')),norm(r.get('to_club_name'))
            events.append({
                'season':f'{y}/{str(y+1)[-2:]}','transfer_date':r.get('transfer_date',''),
                'window':date_window(r.get('transfer_date',''),y),'player_id':r.get('player_id',''),
                'player_name':r.get('player_name',''),'from_club':r.get('from_club_name',''),
                'to_club':r.get('to_club_name',''),'from_is_serie_a':int(fn in cmap),'to_is_serie_a':int(tn in cmap),
                'transfer_fee':r.get('transfer_fee',''),'market_value_in_eur':r.get('market_value_in_eur',''),
                'source':'dcaribou/transfermarkt-datasets'
            })
        # Team-side faces derived deterministically from unique events.
        faces=[]
        for e in events:
            if e['from_is_serie_a']:
                faces.append({**e,'team':cmap[norm(e['from_club'])],'movement':'out','dealing_club':e['to_club']})
            if e['to_is_serie_a']:
                faces.append({**e,'team':cmap[norm(e['to_club'])],'movement':'in','dealing_club':e['from_club']})

        # Independent eordo coverage check, keyed by Transfermarkt player id + directed clubs.
        event_keys=Counter((str(e['player_id']),norm(e['from_club']),norm(e['to_club'])) for e in events)
        unmatched=[]
        for r in erows:
            team=r['club']; cp=r.get('dealing_club',''); mov=r.get('movement','').lower()
            origin=cp if mov=='in' else team; dest=team if mov=='in' else cp
            k=(str(r.get('player_id','')),norm(origin),norm(dest))
            if event_keys[k]>0: event_keys[k]-=1
            else: unmatched.append({'club':team,'movement':mov,'player_name':r.get('player_name'),'player_id':r.get('player_id'),'dealing_club':cp,'window':r.get('window')})

        sd=OUT/str(y); sd.mkdir(parents=True,exist_ok=True)
        def write(name, rows):
            p=sd/name
            if rows:
                with p.open('w',newline='',encoding='utf-8') as f:
                    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
            return p
        ep=write('unique-events.csv',events); fp=write('team-side.csv',faces); up=write('unmatched-eordo.csv',unmatched)
        manifest={
            'season':f'{y}/{str(y+1)[-2:]}','clubCount':20,'clubs':clubs,
            'uniqueEvents':len(events),'teamSideFaces':len(faces),
            'incomingFaces':sum(f['movement']=='in' for f in faces),'outgoingFaces':sum(f['movement']=='out' for f in faces),
            'internalSerieAEvents':sum(e['from_is_serie_a'] and e['to_is_serie_a'] for e in events),
            'summerEvents':sum(e['window']=='summer' for e in events),'winterEvents':sum(e['window']=='winter' for e in events),
            'eordoRows':len(erows),'eordoUnmatchedRows':len(unmatched),'eordoCoverageRatio':round((len(erows)-len(unmatched))/len(erows),6),
            'eordoSourceSha256':sha(b),'dcaribouGlobalGzipSha256':sha(gz),
            'uniqueEventsSha256':sha(ep.read_bytes()),'teamSideSha256':sha(fp.read_bytes()),
            'status':'PASS' if not unmatched else 'FAIL_CROSSCHECK'
        }
        (sd/'manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding='utf-8')
        manifests.append(manifest)

    summary={'schema':'NEXUS_SERIE_A_DATASET_BACKED_TRANSFER_LEDGERS_V2','dcaribouTransferRowsGlobal':len(all_transfers),'seasons':manifests,
             'status':'PASS' if all(m['status']=='PASS' for m in manifests) else 'FAIL_CROSSCHECK'}
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(summary,indent=2,ensure_ascii=False))
    if summary['status']!='PASS': raise SystemExit(2)
if __name__=='__main__': main()
