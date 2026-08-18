from __future__ import annotations
import json,re
from pathlib import Path
from urllib.parse import urljoin,urlparse
import requests
from bs4 import BeautifulSoup

OUT=Path('.nexus-probe-fantasy-efl-public-surface-v1-status/RESULT.json')
START='https://fantasy.efl.com/'
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept-Language':'en-GB,en;q=0.9'}
QUOTED=re.compile(r"[\"']([^\"']{2,500})[\"']")
TERMS=['api','player','players','stats','statistics','competition','season','fantasy','fixture','club','team','genius','feed','standings']

def get(u):return requests.get(u,headers=HEADERS,timeout=35,allow_redirects=True)
def contexts(text,term,r=700,limit=25):
    out=[];low=text.lower();t=term.lower();start=0
    while len(out)<limit:
        i=low.find(t,start)
        if i<0:break
        out.append(text[max(0,i-r):min(len(text),i+len(t)+r)]);start=i+len(t)
    return out

def main():
    r=get(START);soup=BeautifulSoup(r.content,'lxml');host=urlparse(r.url).netloc
    scripts=[]
    for s in soup.find_all('script',src=True):
        u=urljoin(r.url,s.get('src'))
        if u not in scripts:scripts.append(u)
    result={'schema':'NEXUS_FANTASY_EFL_PUBLIC_SURFACE_PROBE_V1','homepage':{'status':r.status_code,'url':r.url,'bytes':len(r.content),'content_type':r.headers.get('content-type'),'text_preview':' '.join(soup.stripped_strings)[:1800]},'scripts':scripts,'assets':[],'candidate_urls':[],'tests':[]}
    candidates=set()
    for u in scripts[:50]:
        if urlparse(u).netloc not in {host,'www.'+host,host.removeprefix('www.')} and not any(x in urlparse(u).netloc for x in ['efl','genius','fantasy']):continue
        try:
            sr=get(u);text=sr.text;rec={'url':u,'status':sr.status_code,'bytes':len(sr.content),'contexts':{}}
            for term in TERMS:
                cc=contexts(text,term)
                if cc:rec['contexts'][term]=cc
            strings=[]
            for q in QUOTED.findall(text):
                ql=q.lower()
                if any(k in ql for k in ['api','player','stat','competition','season','fixture','genius','feed']):
                    strings.append(q)
                    if q.startswith('http'):candidates.add(q)
                    elif q.startswith('/') and any(k in ql for k in ['api','player','stat','competition','season','fixture']):candidates.add(urljoin(r.url,q))
            rec['interesting_strings']=sorted(set(strings))[:1200];result['assets'].append(rec)
        except Exception as exc:result['assets'].append({'url':u,'error':str(exc)})
    result['candidate_urls']=sorted(candidates)
    # Only GET literal same-game URLs; no Genius commercial endpoints, auth, login or mutations.
    for u in result['candidate_urls']:
        ul=u.lower()
        if any(x in ul for x in ['auth','login','register','oauth','token']) or 'api.geniussports.com' in ul:continue
        if '${' in u or '{' in u:continue
        if not any(x in urlparse(u).netloc for x in ['efl','fantasy']):continue
        try:
            rr=get(u);rec={'url':u,'status':rr.status_code,'final_url':rr.url,'content_type':rr.headers.get('content-type'),'bytes':len(rr.content),'preview':rr.text[:1000]}
            try:o=rr.json();rec['json_type']=type(o).__name__;rec['json_keys']=sorted(o.keys()) if isinstance(o,dict) else None;rec['json_len']=len(o) if isinstance(o,(dict,list)) else None
            except Exception:pass
            result['tests'].append(rec)
        except Exception as exc:result['tests'].append({'url':u,'error':str(exc)})
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'homepage':result['homepage'],'candidate_urls':result['candidate_urls'],'tests':result['tests'],'asset_summary':[{'url':x.get('url'),'terms':list((x.get('contexts') or {}).keys()),'strings':x.get('interesting_strings',[])[:80]} for x in result['assets']]},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
