#!/usr/bin/env python3
import json,time,re
from pathlib import Path
from urllib.parse import quote
import requests

OUT=Path('artifacts/n1b-wayback-match-program-probe-v1'); OUT.mkdir(parents=True,exist_ok=True)
S=requests.Session(); S.headers.update({'User-Agent':'FantaNexus-N1B-Wayback-Probe/1.1'})
HASH='632862b6'
FILENAMES=[
 '2021-22_A_UNICO_UNI_1_INTGEN.pdf',
 '2021-22_A_UNICO_UNI_1_VERSAS.pdf',
 '2021-22_A_UNICO_UNI_1_SAMMIL.pdf',
 '2021-22_A_UNICO_UNI_5_ROMUDI.pdf',
 '2021-22_A_UNICO_UNI_10_NAPBOL.pdf',
 '2021-22_A_UNICO_UNI_15_LAZUDI.pdf',
 '2021-22_A_UNICO_UNI_21_GENSPE.pdf',
 '2021-22_A_UNICO_UNI_26_FIOATA.pdf',
 '2021-22_A_UNICO_UNI_29_MILEMP.pdf',
 '2021-22_A_UNICO_UNI_31_ATANAP.pdf',
 '2021-22_A_UNICO_UNI_38_VENCAG.pdf',
]
rows=[]
for fn in FILENAMES:
    rec={'filename':fn}
    exact=f'https://img.legaseriea.it/vimages/{HASH}/{fn}'
    rec['exact_url']=exact
    try:
        api='https://archive.org/wayback/available?url='+quote(exact,safe='')+'&timestamp=20220920000000'
        r=S.get(api,timeout=30)
        rec['availability_http']=r.status_code
        payload=r.json(); rec['availability']=payload
        cl=(payload.get('archived_snapshots') or {}).get('closest') or {}
        rec['available_200']=bool(cl.get('available') is True and str(cl.get('status'))=='200')
        if cl:
            rec['capture_timestamp']=cl.get('timestamp'); rec['snapshot_url']=cl.get('url')
    except Exception as e:
        rec['error']=f'{type(e).__name__}:{e}'
    rows.append(rec)
    time.sleep(.4)
summary={'hash':HASH,'hash_as_unix':int(HASH,16),'tested':len(rows),'available_200':sum(r.get('available_200') is True for r in rows),'known_positive_filename':'2021-22_A_UNICO_UNI_29_MILEMP.pdf','rows':rows}
(OUT/'probe.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(summary,indent=2,ensure_ascii=False))
