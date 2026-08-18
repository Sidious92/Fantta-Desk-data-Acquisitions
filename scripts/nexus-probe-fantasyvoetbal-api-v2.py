from __future__ import annotations
import json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup

OUT=Path('.nexus-probe-fantasyvoetbal-api-v2-status/RESULT.json')
START='https://fantasy.espngoal.nl/'
HEADERS={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/151 Safari/537.36','Accept':'application/json, text/plain, */*','Referer':START}
TERMS=['/api/','search-entries','players','player','gameweeks','gameweek','rounds','teams','clubs','fixtures','matches','stats','statistics','settings','competition','league','transfers','prices']
LITERAL_API=re.compile(r'["\']([^"\']*(?:/api/)[^"\']*)["\']')

def get(url,accept=None):
    h=dict(HEADERS)
    if accept: h['Accept']=accept
    return requests.get(url,headers=h,timeout=35,allow_redirects=True)

def contexts(text,needle,radius=700,limit=30):
    out=[]; start=0
    while len(out)<limit:
        i=text.find(needle,start)
        if i<0: break
        out.append(text[max(0,i-radius):min(len(text),i+len(needle)+radius)])
        start=i+len(needle)
    return out

def main():
    hr=get(START,'text/html,*/*'); soup=BeautifulSoup(hr.content,'lxml')
    scripts=[urljoin(hr.url,s.get('src')) for s in soup.find_all('script',src=True) if 'fantasy.espngoal.nl' in urljoin(hr.url,s.get('src'))]
    result={'schema':'NEXUS_FANTASYVOETBAL_API_PROBE_V2','homepage_status':hr.status_code,'scripts':scripts,'assets':[],'literal_api_candidates':[],'tests':[]}
    literals=set()
    for u in scripts:
        try:
            r=get(u,'*/*'); text=r.text
            rec={'url':u,'status':r.status_code,'bytes':len(r.content),'contexts':{}}
            for term in TERMS:
                cc=contexts(text,term,600,20)
                if cc: rec['contexts'][term]=cc
            for x in LITERAL_API.findall(text):
                if len(x)<500: literals.add(x)
            # Capture quoted route-like strings near relevant vocabulary.
            strings=re.findall(r'["\']([^"\']{2,180})["\']',text)
            rec['interesting_strings']=sorted({s for s in strings if any(t.strip('/').lower() in s.lower() for t in ['player','gameweek','fixture','match','team','club','stat','competition','league','transfer'])})[:1200]
            result['assets'].append(rec)
        except Exception as exc: result['assets'].append({'url':u,'error':str(exc)})
    result['literal_api_candidates']=sorted(literals)
    # Only test literal static API paths: no templates, variables, login or mutation routes.
    for p in sorted(literals):
        if '${' in p or '{' in p or any(x in p.lower() for x in ['login','logout','register','password','team/create','transfer/']): continue
        if not p.startswith('/api/'): continue
        try:
            r=get(urljoin(START,p))
            rec={'path':p,'status':r.status_code,'final_url':r.url,'content_type':r.headers.get('content-type'),'bytes':len(r.content),'preview':r.text[:1200]}
            try:
                obj=r.json(); rec['json_type']=type(obj).__name__; rec['json_keys']=sorted(obj.keys()) if isinstance(obj,dict) else None; rec['json_len']=len(obj) if isinstance(obj,(dict,list)) else None
            except Exception: pass
            result['tests'].append(rec)
        except Exception as exc: result['tests'].append({'path':p,'error':str(exc)})
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'literal_api_candidates':result['literal_api_candidates'],'tests':result['tests'],'asset_summary':[{'url':x.get('url'),'bytes':x.get('bytes'),'context_terms':list((x.get('contexts') or {}).keys()),'interesting_string_count':len(x.get('interesting_strings') or [])} for x in result['assets']]},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
