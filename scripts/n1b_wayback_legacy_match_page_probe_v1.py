#!/usr/bin/env python3
import json,re
from pathlib import Path
from urllib.parse import quote,urljoin
import requests

OUT=Path('artifacts/n1b-wayback-legacy-match-page-probe-v1'); OUT.mkdir(parents=True,exist_ok=True)
S=requests.Session(); S.headers.update({'User-Agent':'FantaNexus-N1B-Legacy-Page-Probe/1.0'})
TARGETS=[
 'http://www.legaseriea.it/it/serie-a/match-report/2021-22/UNICO/UNI/29/MILEMP',
 'https://www.legaseriea.it/it/serie-a/match-report/2021-22/UNICO/UNI/29/MILEMP',
 'http://www.legaseriea.it/it/serie-a-tim/match-report/2021-22/UNICO/UNI/29/MILEMP',
 'https://www.legaseriea.it/it/serie-a-tim/match-report/2021-22/UNICO/UNI/29/MILEMP',
]

def raw_url(snap,ts):
    marker=f'/web/{ts}/'
    if marker in snap:return snap.replace(marker,f'/web/{ts}id_/',1)
    marker=f'/web/{ts}if_/'
    if marker in snap:return snap.replace(marker,f'/web/{ts}id_/',1)
    return snap

rows=[]
for target in TARGETS:
    rec={'target':target}
    try:
        api='https://archive.org/wayback/available?url='+quote(target,safe='')+'&timestamp=20220313000000'
        a=S.get(api,timeout=30); rec['availability_http']=a.status_code; payload=a.json(); rec['availability']=payload
        cl=(payload.get('archived_snapshots') or {}).get('closest') or {}
        if cl.get('available') and str(cl.get('status'))=='200':
            ts=str(cl.get('timestamp')); snap=str(cl.get('url')); ru=raw_url(snap,ts)
            q=S.get(ru,timeout=40,allow_redirects=True)
            rec.update({'capture_ts':ts,'snapshot_url':snap,'raw_url':ru,'page_http':q.status_code,'page_bytes':len(q.content),'final_url':q.url})
            text=q.text
            # retain any candidate PDF/vimages URLs and nearby Match Program anchors/text
            urls=[]
            raw=text.replace('\\/','/')
            for m in re.finditer(r'https?://[^\"\'<> ]+(?:\.pdf|vimages/[^\"\'<> ]+)',raw,re.I):
                u=m.group(0)
                near=raw[max(0,m.start()-300):m.end()+300].lower()
                if 'match program' in near or 'matchprogram' in near or 'vimages' in u.lower():
                    urls.append(u)
            for m in re.finditer(r'href=[\"\']([^\"\']+)[\"\']',raw,re.I):
                href=m.group(1)
                near=raw[max(0,m.start()-300):m.end()+300].lower()
                if 'match program' in near or 'matchprogram' in near:
                    urls.append(urljoin(target,href))
            rec['candidate_urls']=list(dict.fromkeys(urls))[:50]
            rec['contains_known_filename']='2021-22_A_UNICO_UNI_29_MILEMP.pdf' in text
            rec['contains_match_program_phrase']='match program' in text.lower() or 'matchprogram' in text.lower()
    except Exception as e:
        rec['error']=f'{type(e).__name__}:{e}'
    rows.append(rec)
(OUT/'probe.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(rows,ensure_ascii=False,indent=2))
