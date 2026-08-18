from __future__ import annotations
import json,re
from pathlib import Path
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup

OUT=Path('.nexus-probe-mls-fantasy-legacy-public-v1-status/RESULT.json')
PAGES=['https://fantasy.mlssoccer.com/stats/players/','https://fantasy.mlssoccer.com/players/']
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept-Language':'en-US,en;q=0.9'}
QUOTED=re.compile(r"[\"']([^\"']{2,500})[\"']")
TERMS=['api','player','stats','fantasy','points','price','form','selected','team','club','roster','data']

def get(u):return requests.get(u,headers=HEADERS,timeout=35,allow_redirects=True)
def contexts(text,term,r=600,limit=20):
    out=[];low=text.lower();t=term.lower();s=0
    while len(out)<limit:
        i=low.find(t,s)
        if i<0:break
        out.append(text[max(0,i-r):min(len(text),i+len(t)+r)]);s=i+len(t)
    return out

def main():
    result={'schema':'NEXUS_MLS_FANTASY_LEGACY_PUBLIC_PROBE_V1','pages':[],'assets':[],'candidate_urls':[],'tests':[]}
    scripts=[];cands=set();hosts=set()
    for u in PAGES:
        try:
            r=get(u);hosts.add(urlparse(r.url).netloc);soup=BeautifulSoup(r.content,'lxml')
            result['pages'].append({'requested':u,'status':r.status_code,'final_url':r.url,'bytes':len(r.content),'content_type':r.headers.get('content-type'),'title':soup.title.get_text(' ',strip=True) if soup.title else None,'text_preview':' '.join(soup.stripped_strings)[:1800]})
            for s in soup.find_all('script',src=True):
                su=urljoin(r.url,s.get('src'))
                if su not in scripts:scripts.append(su)
        except Exception as exc:result['pages'].append({'requested':u,'error':str(exc)})
    result['scripts']=scripts
    for u in scripts[:60]:
        if not any(x in urlparse(u).netloc for x in ['mls','fantasy','sportec','ism','kickbase']):continue
        try:
            r=get(u);text=r.text;rec={'url':u,'status':r.status_code,'bytes':len(r.content),'contexts':{}}
            for t in TERMS:
                cc=contexts(text,t)
                if cc:rec['contexts'][t]=cc
            strings=[]
            for q in QUOTED.findall(text):
                ql=q.lower()
                if any(k in ql for k in ['api','player','stat','fantasy','point','roster']):
                    strings.append(q)
                    if q.startswith('http'):cands.add(q)
                    elif q.startswith('/') and any(k in ql for k in ['api','player','stat','roster']):cands.add(urljoin('https://fantasy.mlssoccer.com/',q))
            rec['interesting_strings']=sorted(set(strings))[:1000];result['assets'].append(rec)
        except Exception as exc:result['assets'].append({'url':u,'error':str(exc)})
    result['candidate_urls']=sorted(cands)
    for u in result['candidate_urls']:
        if '${' in u or '{' in u or any(x in u.lower() for x in ['login','auth','token']):continue
        if not any(x in urlparse(u).netloc for x in ['mls','fantasy']):continue
        try:
            r=get(u);rec={'url':u,'status':r.status_code,'final_url':r.url,'content_type':r.headers.get('content-type'),'bytes':len(r.content),'preview':r.text[:1000]}
            try:o=r.json();rec['json_type']=type(o).__name__;rec['json_keys']=sorted(o.keys()) if isinstance(o,dict) else None;rec['json_len']=len(o) if isinstance(o,(dict,list)) else None
            except Exception:pass
            result['tests'].append(rec)
        except Exception as exc:result['tests'].append({'url':u,'error':str(exc)})
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'pages':result['pages'],'candidate_urls':result['candidate_urls'],'tests':result['tests'],'asset_summary':[{'url':x.get('url'),'terms':list((x.get('contexts') or {}).keys()),'strings':x.get('interesting_strings',[])[:60]} for x in result['assets']]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
