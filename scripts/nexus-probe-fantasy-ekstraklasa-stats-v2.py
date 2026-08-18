from __future__ import annotations
import json,re
from pathlib import Path
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup

OUT=Path('.nexus-probe-fantasy-ekstraklasa-stats-v2-status/RESULT.json')
START='https://fantasy.ekstraklasa.org/stats'
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept-Language':'pl,en;q=0.8','X-Requested-With':'XMLHttpRequest'}
QUOTED=re.compile(r"[\"']([^\"']{2,350})[\"']")

def get(u,params=None): return requests.get(u,params=params or {},headers=HEADERS,timeout=35,allow_redirects=True)
def contexts(text,terms,r=600):
    out={}
    low=text.lower()
    for term in terms:
        arr=[]; start=0; t=term.lower()
        while len(arr)<25:
            i=low.find(t,start)
            if i<0: break
            arr.append(text[max(0,i-r):min(len(text),i+len(term)+r)]); start=i+len(t)
        if arr: out[term]=arr
    return out

def main():
    r=get(START); soup=BeautifulSoup(r.content,'lxml'); host=urlparse(r.url).netloc
    result={'schema':'NEXUS_FANTASY_EKSTRAKLASA_STATS_PROBE_V2','page':{'status':r.status_code,'url':r.url,'bytes':len(r.content)},'forms':[],'inline_contexts':{},'data_attrs':[],'scripts':[],'route_candidates':[],'tests':[]}
    for f in soup.find_all('form'):
        result['forms'].append({'method':(f.get('method') or 'GET').upper(),'action':urljoin(r.url,f.get('action') or ''),'id':f.get('id'),'class':f.get('class'),'fields':[{'tag':x.name,'name':x.get('name'),'type':x.get('type'),'value':x.get('value'),'id':x.get('id')} for x in f.find_all(['input','select','button'])]})
    for tag in soup.find_all(True):
        attrs={k:v for k,v in tag.attrs.items() if str(k).startswith('data-')}
        if attrs: result['data_attrs'].append({'tag':tag.name,'id':tag.get('id'),'class':tag.get('class'),'attrs':attrs})
    inline='\n'.join(s.get_text('\n') for s in soup.find_all('script') if not s.get('src'))
    terms=['ajax','fetch(','$.get','$.post','stats','player','zawod','points','punkty','datatable','DataTable','loading','ładowanie','stats-game']
    result['inline_contexts']=contexts(inline,terms)
    routes=set()
    for s in QUOTED.findall(inline):
        sl=s.lower()
        if any(k in sl for k in ['stats','ajax','player','zawod','point','punk','game','mecz']):
            if s.startswith('/') or s.startswith('http'): routes.add(urljoin(r.url,s) if s.startswith('/') else s)
    scripts=[]
    for s in soup.find_all('script',src=True):
        u=urljoin(r.url,s.get('src'))
        if u in scripts: continue
        scripts.append(u)
        if urlparse(u).netloc not in {host,'www.'+host,host.removeprefix('www.')} and 'ekstraklasa' not in urlparse(u).netloc: continue
        try:
            sr=get(u); text=sr.text; cc=contexts(text,terms,500)
            strings=[]
            for q in QUOTED.findall(text):
                ql=q.lower()
                if any(k in ql for k in ['stats','ajax','player','zawod','point','punk','game','mecz']): strings.append(q)
                if (q.startswith('/') or q.startswith('http')) and any(k in ql for k in ['stats','player','zawod','point','punk','game','mecz']): routes.add(urljoin(r.url,q) if q.startswith('/') else q)
            result['scripts'].append({'url':u,'status':sr.status_code,'bytes':len(sr.content),'contexts':cc,'interesting_strings':sorted(set(strings))[:500]})
        except Exception as exc: result['scripts'].append({'url':u,'error':str(exc)})
    result['route_candidates']=sorted(routes)
    # Read-only GET tests only, limited to static literal routes on same host.
    for u in result['route_candidates']:
        if urlparse(u).netloc!=host or any(x in u.lower() for x in ['login','register','premium']): continue
        try:
            rr=get(u); rec={'url':u,'status':rr.status_code,'final_url':rr.url,'content_type':rr.headers.get('content-type'),'bytes':len(rr.content),'preview':rr.text[:1000]}
            try:
                o=rr.json(); rec['json_type']=type(o).__name__; rec['json_keys']=sorted(o.keys()) if isinstance(o,dict) else None; rec['json_len']=len(o) if isinstance(o,(dict,list)) else None
            except Exception: pass
            result['tests'].append(rec)
        except Exception as exc: result['tests'].append({'url':u,'error':str(exc)})
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'forms':result['forms'],'route_candidates':result['route_candidates'],'tests':result['tests'],'inline_terms':list(result['inline_contexts']),'script_summaries':[{'url':x.get('url'),'context_terms':list((x.get('contexts') or {})),'interesting_strings':x.get('interesting_strings',[])[:50]} for x in result['scripts']]},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
