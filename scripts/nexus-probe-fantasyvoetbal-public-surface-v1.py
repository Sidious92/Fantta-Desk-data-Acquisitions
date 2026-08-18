from __future__ import annotations
import json,re
from pathlib import Path
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup

OUT=Path('.nexus-probe-fantasyvoetbal-public-surface-v1-status/RESULT.json')
START='https://fantasyvoetbal.nl/'
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept-Language':'en-US,en;q=0.8,nl;q=0.6'}
URL_RE=re.compile(r'https?://[^\"\'\s)]+')
API_RE=re.compile(r'(?:(?:https?:)?//[^\"\'\s)]+/api/[^\"\'\s)]*|/api/[A-Za-z0-9_./?=&%{}:$-]+)')
GRAPH_RE=re.compile(r'[^\"\'\s]{0,80}(?:graphql|GraphQL)[^\"\'\s]{0,160}')

def get(url):
    r=requests.get(url,headers=HEADERS,timeout=30,allow_redirects=True)
    return r

def main():
    result={'schema':'NEXUS_FANTASYVOETBAL_PUBLIC_SURFACE_PROBE_V1','start_url':START}
    try:
        r=get(START)
        result['homepage']={'status':r.status_code,'final_url':r.url,'content_type':r.headers.get('content-type'),'bytes':len(r.content),'text_preview':r.text[:1500]}
        soup=BeautifulSoup(r.content,'lxml')
        scripts=[]
        for s in soup.find_all('script',src=True):
            u=urljoin(r.url,s.get('src'))
            if u not in scripts: scripts.append(u)
        links=[]
        for a in soup.find_all('a',href=True):
            u=urljoin(r.url,a.get('href'))
            if u not in links: links.append(u)
        result['script_urls']=scripts[:80]
        result['link_urls']=links[:120]
        assets=[]; endpoints=set(); external_urls=set(); graph_hits=set()
        base_host=urlparse(r.url).netloc
        for u in scripts[:35]:
            if urlparse(u).netloc not in {base_host,'www.'+base_host,base_host.removeprefix('www.')}:
                continue
            try:
                sr=get(u)
                txt=sr.text
                rec={'url':u,'status':sr.status_code,'bytes':len(sr.content),'content_type':sr.headers.get('content-type')}
                for m in API_RE.findall(txt): endpoints.add(m)
                for m in URL_RE.findall(txt):
                    if any(x in m.lower() for x in ['api','graphql','fantasy','espn']): external_urls.add(m[:500])
                for m in GRAPH_RE.findall(txt): graph_hits.add(m[:500])
                rec['api_hits']=sorted(set(API_RE.findall(txt)))[:100]
                assets.append(rec)
            except Exception as exc: assets.append({'url':u,'error':str(exc)})
        result['assets']=assets
        result['api_candidates']=sorted(endpoints)
        result['interesting_urls']=sorted(external_urls)
        result['graphql_hits']=sorted(graph_hits)
        for extra in ['/robots.txt','/manifest.json','/site.webmanifest','/.well-known/assetlinks.json']:
            try:
                er=get(urljoin(r.url,extra)); result.setdefault('extras',[]).append({'path':extra,'status':er.status_code,'final_url':er.url,'bytes':len(er.content),'preview':er.text[:2000]})
            except Exception as exc: result.setdefault('extras',[]).append({'path':extra,'error':str(exc)})
    except Exception as exc:
        result['error']=str(exc)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'homepage':result.get('homepage'),'scripts':len(result.get('script_urls',[])),'api_candidates':result.get('api_candidates',[])[:30],'interesting_urls':result.get('interesting_urls',[])[:30]},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
