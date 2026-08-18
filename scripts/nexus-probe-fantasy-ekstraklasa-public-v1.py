from __future__ import annotations
import json,re
from pathlib import Path
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup

OUT=Path('.nexus-probe-fantasy-ekstraklasa-public-v1-status/RESULT.json')
START='https://fantasy.ekstraklasa.org/'
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept-Language':'pl,en;q=0.8'}
PATH_RE=re.compile(r"(?:(?:https?:)?//[^\"'\s)]+|/[A-Za-z0-9_./?=&%{}:$-]+)")

def get(u): return requests.get(u,headers=HEADERS,timeout=35,allow_redirects=True)
def main():
    r=get(START); soup=BeautifulSoup(r.content,'lxml'); host=urlparse(r.url).netloc
    scripts=[]
    for s in soup.find_all('script',src=True):
        u=urljoin(r.url,s.get('src'))
        if u not in scripts: scripts.append(u)
    links=[{'text':' '.join(a.stripped_strings)[:120],'url':urljoin(r.url,a.get('href'))} for a in soup.find_all('a',href=True)]
    result={'schema':'NEXUS_FANTASY_EKSTRAKLASA_PUBLIC_PROBE_V1','homepage':{'status':r.status_code,'url':r.url,'bytes':len(r.content),'content_type':r.headers.get('content-type')},'scripts':scripts,'links':links,'assets':[],'api_candidates':[]}
    api=set()
    for u in scripts[:50]:
        if urlparse(u).netloc not in {host,'www.'+host,host.removeprefix('www.')} and not any(k in urlparse(u).netloc for k in ['ekstraklasa','fantasy']): continue
        try:
            sr=get(u); text=sr.text; hits=[]
            for m in PATH_RE.findall(text):
                ml=m.lower()
                if any(k in ml for k in ['/api/','api.','player','zawodnik','ranking','points','punkty','gameweek','kolejka','fixture','mecz','stats','statysty']):
                    resolved=urljoin(r.url,m) if m.startswith('/') else m; hits.append(resolved)
                    if '/api/' in ml or 'api.' in ml: api.add(resolved)
            result['assets'].append({'url':u,'status':sr.status_code,'bytes':len(sr.content),'hits':sorted(set(hits))[:500]})
        except Exception as exc: result['assets'].append({'url':u,'error':str(exc)})
    result['api_candidates']=sorted(api)
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'homepage':result['homepage'],'scripts':scripts,'api_candidates':result['api_candidates'][:100],'asset_hits':[{'url':x.get('url'),'hits':x.get('hits',[])[:50]} for x in result['assets']]},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
