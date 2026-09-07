#!/usr/bin/env python3
import json, requests, re
from pathlib import Path

BASE_SDP='https://api-sdp.legaseriea.it/v1/serie-a/football'
SID='serie-a::Football_Season::4c67f7c66d484e559a65857eb5a7cbeb'
HASH='632862b6'
OUT=Path('artifacts/n1b-legacy-vimages-batch-probe-v1'); OUT.mkdir(parents=True,exist_ok=True)
S=requests.Session(); S.headers.update({'User-Agent':'FantaNexus-N1B-Legacy-Probe/1.0'})

def acr(team):
    # official SDP acronym fields first; fail closed rather than inventing if absent
    for k in ('acronym','shortName','name'):
        v=(team or {}).get(k)
        if k=='acronym' and v: return re.sub(r'[^A-Z0-9]','',v.upper())
    return None

r=S.get(f'{BASE_SDP}/seasons/{SID}/matches?locale=en-GB',timeout=20); r.raise_for_status()
ms=r.json().get('matches') or []
# deterministic spread across season
idx=[0,1,9,49,99,149,199,249,299,349,379]
rows=[]
for i in idx:
    m=ms[i]
    rnd=((m.get('matchSet') or {}).get('index'))
    home=m.get('home') or {}; away=m.get('away') or {}
    ha=acr(home); aa=acr(away)
    # providerId is authoritative and already embeds the historical filename token; use it when possible
    pid=m.get('providerId') or ''
    mm=re.search(r'2021-22AUNICOUNI(\d+)([A-Z0-9]+)$',pid)
    if mm:
        rnd=int(mm.group(1)); token=mm.group(2)
    else:
        token=(ha or '')+(aa or '')
    fn=f'2021-22_A_UNICO_UNI_{rnd}_{token}.pdf'
    url=f'https://img.legaseriea.it/vimages/{HASH}/{fn}'
    try:
        q=S.get(url,timeout=15,allow_redirects=True)
        rows.append({'index':i,'round':rnd,'home':home.get('shortName'),'away':away.get('shortName'),'providerId':pid,'filename':fn,'url':url,'http':q.status_code,'is_pdf':q.content.startswith(b'%PDF'),'bytes':len(q.content),'final_url':q.url})
    except Exception as e:
        rows.append({'index':i,'round':rnd,'home':home.get('shortName'),'away':away.get('shortName'),'providerId':pid,'filename':fn,'url':url,'error':f'{type(e).__name__}:{e}'})
(OUT/'probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(rows,ensure_ascii=False,indent=2))
