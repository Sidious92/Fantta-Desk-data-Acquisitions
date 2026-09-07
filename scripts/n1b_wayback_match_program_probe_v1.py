#!/usr/bin/env python3
import json, time
from pathlib import Path
from urllib.parse import urlencode
import requests

OUT=Path('artifacts/n1b-wayback-match-program-probe-v1'); OUT.mkdir(parents=True,exist_ok=True)
S=requests.Session(); S.headers.update({'User-Agent':'FantaNexus-N1B-Wayback-Probe/1.0'})
filename='2021-22_A_UNICO_UNI_29_MILEMP.pdf'
variants=[
 ('wildcard_exact',{'url':f'img.legaseriea.it/vimages/*/{filename}','output':'json','fl':'timestamp,original,statuscode,mimetype,digest','filter':'statuscode:200','collapse':'urlkey'}),
 ('wildcard_exact_http',{'url':f'http://img.legaseriea.it/vimages/*/{filename}','output':'json','fl':'timestamp,original,statuscode,mimetype,digest','filter':'statuscode:200','collapse':'urlkey'}),
 ('prefix_filter',{'url':'img.legaseriea.it/vimages/*','output':'json','fl':'timestamp,original,statuscode,mimetype,digest','filter':[f'original:.*{filename.replace(".","\\.")}$','statuscode:200'],'collapse':'urlkey','limit':'50'}),
]
rows=[]
for name,params in variants:
    try:
        url='https://web.archive.org/cdx/search/cdx?'+urlencode(params,doseq=True)
        r=S.get(url,timeout=45)
        rows.append({'name':name,'url':url,'http':r.status_code,'content_type':r.headers.get('content-type'),'text_prefix':r.text[:4000]})
    except Exception as e:
        rows.append({'name':name,'error':f'{type(e).__name__}:{e}'})
    time.sleep(1)
(OUT/'probe.json').write_text(json.dumps(rows,indent=2,ensure_ascii=False),encoding='utf-8')
print(json.dumps(rows,indent=2,ensure_ascii=False))
