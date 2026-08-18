from __future__ import annotations
import json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

OUT=Path('.nexus-probe-belgian-fantasy-config-v2-status/RESULT.json')
START='https://fantasy.proleague.be/stats'
HEADERS={'User-Agent':'Mozilla/5.0 Chrome/151','Accept':'application/json, text/plain, */*','Referer':START}
TERMS=['competitionFeed','seasonId','application.competition','fanarena','competition','season','feed','environment','apiUrl','apiBase','config']
QUOTED=re.compile(r"[\"']([^\"']{2,500})[\"']")

def get(u):return requests.get(u,headers=HEADERS,timeout=35,allow_redirects=True)
def contexts(text,term,r=1400,limit=30):
    out=[];start=0
    while len(out)<limit:
        i=text.find(term,start)
        if i<0:break
        out.append(text[max(0,i-r):min(len(text),i+len(term)+r)]);start=i+len(term)
    return out

def main():
    r=get(START);soup=BeautifulSoup(r.content,'lxml');scripts=[urljoin(r.url,s.get('src')) for s in soup.find_all('script',src=True)]
    result={'schema':'NEXUS_BELGIAN_FANTASY_CONFIG_PROBE_V2','scripts':scripts,'assets':[],'candidate_urls':[]}
    urls=set()
    for u in scripts:
        try:
            sr=get(u);text=sr.text;rec={'url':u,'status':sr.status_code,'bytes':len(sr.content),'contexts':{}}
            for term in TERMS:
                cc=contexts(text,term)
                if cc:rec['contexts'][term]=cc
            strings=[]
            for q in QUOTED.findall(text):
                ql=q.lower()
                if any(k in ql for k in ['http','api','config','competition','season','feed','fanarena']):
                    strings.append(q)
                    if q.startswith('http'):urls.add(q)
                    elif q.startswith('/') and any(k in ql for k in ['api','config','competition','season']):urls.add(urljoin(r.url,q))
            rec['interesting_strings']=sorted(set(strings))[:1500]
            result['assets'].append(rec)
        except Exception as exc:result['assets'].append({'url':u,'error':str(exc)})
    result['candidate_urls']=sorted(urls)
    result['url_tests']=[]
    for u in sorted(urls):
        if '${' in u or '{' in u or len(u)>500:continue
        if not any(host in u for host in ['fantasy.proleague.be','fanarena','proleague']):continue
        try:
            rr=get(u);rec={'url':u,'status':rr.status_code,'final_url':rr.url,'content_type':rr.headers.get('content-type'),'bytes':len(rr.content),'preview':rr.text[:1400]}
            try:o=rr.json();rec['json_type']=type(o).__name__;rec['json_keys']=sorted(o.keys()) if isinstance(o,dict) else None;rec['json_len']=len(o) if isinstance(o,(dict,list)) else None
            except Exception:pass
            result['url_tests'].append(rec)
        except Exception as exc:result['url_tests'].append({'url':u,'error':str(exc)})
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'candidate_urls':result['candidate_urls'],'url_tests':result['url_tests'],'asset_context_terms':[{'url':x.get('url'),'terms':list((x.get('contexts') or {}).keys())} for x in result['assets']]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
