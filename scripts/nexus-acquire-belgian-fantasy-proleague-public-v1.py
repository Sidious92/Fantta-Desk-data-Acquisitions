from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT=Path(os.environ.get('NEXUS_BELGIAN_FANTASY_OUT','/mnt/data/nexus-belgian-fantasy-proleague-public-v1'))
START='https://fantasy.proleague.be/stats'
HEADERS={
    'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36',
    'Accept-Language':'en-US,en;q=0.9,nl;q=0.7',
}
URL_RE=re.compile(r'https?://[^\"\'\s)]+')
PATH_RE=re.compile(r'(?:(?:https?:)?//[^\"\'\s)]+|/[A-Za-z0-9_./?=&%{}:$-]+)')

def sha(b): return hashlib.sha256(b).hexdigest()
def mkdir(p): p.mkdir(parents=True,exist_ok=True); return p
def save_json(p,obj): mkdir(p.parent); p.write_text(json.dumps(obj,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
def get(url): return requests.get(url,headers=HEADERS,timeout=35,allow_redirects=True)
def is_sheet_url(u):
    x=u.lower().split('?')[0]
    return x.endswith(('.xlsx','.xls','.csv')) or any(k in u.lower() for k in ['excel','player-list','playerlist','export'])

def main():
    mkdir(OUT); raw=mkdir(OUT/'raw')
    result={'schema':'NEXUS_BELGIAN_FANTASY_PROLEAGUE_PUBLIC_V1','start_url':START,'downloads':[],'api_candidates':[],'status':'PROBE'}
    r=get(START); (raw/'stats-page.html').write_bytes(r.content)
    result['page']={'status':r.status_code,'final_url':r.url,'content_type':r.headers.get('content-type'),'bytes':len(r.content),'sha256':sha(r.content)}
    soup=BeautifulSoup(r.content,'lxml')
    hrefs=[]
    for a in soup.find_all('a',href=True):
        u=urljoin(r.url,a.get('href'))
        hrefs.append({'text':' '.join(a.stripped_strings)[:200],'url':u})
    result['links']=hrefs
    candidates=[x['url'] for x in hrefs if is_sheet_url(x['url']) or 'excel' in x['text'].lower()]
    scripts=[]
    for s in soup.find_all('script',src=True):
        u=urljoin(r.url,s.get('src'))
        if u not in scripts: scripts.append(u)
    result['scripts']=scripts
    same_host=urlparse(r.url).netloc
    api=set(); sheet_candidates=set(candidates); script_records=[]
    for u in scripts[:40]:
        if urlparse(u).netloc not in {same_host,'www.'+same_host,same_host.removeprefix('www.')}:
            continue
        try:
            sr=get(u); text=sr.text
            sp=raw/('script-'+hashlib.sha1(u.encode()).hexdigest()[:12]+'.js'); sp.write_bytes(sr.content)
            hits=[]
            for m in PATH_RE.findall(text):
                ml=m.lower()
                if any(k in ml for k in ['/api/','excel','xlsx','csv','player-list','playerlist','export','stats']):
                    resolved=urljoin(r.url,m) if m.startswith('/') else m
                    hits.append(resolved)
                    if is_sheet_url(resolved): sheet_candidates.add(resolved)
                    if '/api/' in ml or 'api.' in ml: api.add(resolved)
            script_records.append({'url':u,'status':sr.status_code,'bytes':len(sr.content),'sha256':sha(sr.content),'hits':sorted(set(hits))[:250]})
        except Exception as exc:
            script_records.append({'url':u,'error':str(exc)})
    result['script_records']=script_records
    result['api_candidates']=sorted(api)
    result['sheet_candidates']=sorted(sheet_candidates)

    seen=set()
    for u in sorted(sheet_candidates):
        if u in seen or '${' in u or '{' in u: continue
        seen.add(u)
        try:
            dr=get(u); ct=(dr.headers.get('content-type') or '').lower(); b=dr.content
            ext=None
            if b[:4]==b'PK\x03\x04': ext='xlsx'
            elif 'spreadsheet' in ct or 'excel' in ct: ext='xls'
            elif 'csv' in ct or (b and b[:1] not in {b'<',b'{',b'['} and b.count(b',')>3): ext='csv'
            rec={'url':u,'status':dr.status_code,'final_url':dr.url,'content_type':dr.headers.get('content-type'),'bytes':len(b),'sha256':sha(b),'recognized_format':ext}
            if dr.status_code==200 and ext:
                path=raw/f'player-list.{ext}'; path.write_bytes(b); rec['local_path']=str(path.relative_to(OUT))
            result['downloads'].append(rec)
        except Exception as exc: result['downloads'].append({'url':u,'error':str(exc)})
    result['status']='PASS_PUBLIC_DATA' if any(x.get('local_path') for x in result['downloads']) else ('PASS_PUBLIC_SURFACE' if r.status_code==200 else 'FAIL')
    save_json(OUT/'manifest.json',result)
    print(json.dumps({'status':result['status'],'page':result['page'],'sheet_candidates':result['sheet_candidates'],'downloads':result['downloads'],'api_candidates':result['api_candidates'][:50]},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
