#!/usr/bin/env python3
import json,re,hashlib,sys
from urllib.parse import urljoin
from pathlib import Path
import requests

BASE='https://fantasy.ligaportugal.pt/'
OUT=Path('/mnt/data/nexus-liga-portugal-fantasy-probe-v1')
OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition'})

def get(url):
    r=s.get(url,timeout=30,allow_redirects=True)
    return r

def rec(r):
    b=r.content
    return {'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'preview':r.text[:1000] if 'text' in r.headers.get('content-type','') or 'json' in r.headers.get('content-type','') else ''}

result={'schema':'NEXUS_LIGA_PORTUGAL_FANTASY_PUBLIC_PROBE_V1','base':BASE,'pages':{},'scripts':[],'known_endpoint_tests':[],'discovered_api_candidates':[]}
html=''
for name,path in [('home',''),('player_list','player-list'),('rules','help/rules')]:
    try:
        r=get(urljoin(BASE,path)); result['pages'][name]=rec(r)
        if name=='player_list': html=r.text
    except Exception as e: result['pages'][name]={'error':repr(e)}

script_urls=[]
for page in result['pages'].values():
    pv=page.get('preview','')
# refetch player-list fully for scripts
try:
    r=get(urljoin(BASE,'player-list')); full=r.text
    for src in re.findall(r'<script[^>]+src=[\"\']([^\"\']+)',full,re.I):
        script_urls.append(urljoin(r.url,src))
except Exception: full=''

api_cands=set()
for u in dict.fromkeys(script_urls):
    try:
        rr=get(u); txt=rr.text
        info=rec(rr); info['requested']=u
        for pat in [r'[\"\']([^\"\']*(?:/api/|bootstrap-static|element-summary|fixtures|player-list)[^\"\']*)[\"\']']:
            for m in re.findall(pat,txt,re.I):
                if len(m)<300: api_cands.add(m)
        info['contexts']={k:[txt[max(0,m.start()-120):m.end()+220] for m in list(re.finditer(k,txt,re.I))[:8]] for k in ['api','bootstrap','element-summary','player']}
        result['scripts'].append(info)
    except Exception as e: result['scripts'].append({'requested':u,'error':repr(e)})

result['discovered_api_candidates']=sorted(api_cands)[:500]
for path in ['api/bootstrap-static/','api/fixtures/','api/event/1/live/','api/element-summary/1/','api/players/','api/player-list/']:
    url=urljoin(BASE,path)
    try:
        rr=get(url); x=rec(rr); x['requested']=url
        try:
            j=rr.json(); x['json_type']=type(j).__name__; x['json_keys']=list(j)[:40] if isinstance(j,dict) else None; x['json_len']=len(j) if hasattr(j,'__len__') else None
        except Exception: pass
        result['known_endpoint_tests'].append(x)
    except Exception as e: result['known_endpoint_tests'].append({'requested':url,'error':repr(e)})

# Inspect player-list HTML for row structure / embedded JSON
result['player_list_html']={'has_table':bool(re.search(r'<table',full,re.I)),'player_tokens':len(re.findall(r'player',full,re.I)),'next_data':bool(re.search(r'__NEXT_DATA__',full)),'nuxt':bool(re.search(r'__NUXT__',full))}

(OUT/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'pages':{k:v.get('status') for k,v in result['pages'].items()},'scripts':len(result['scripts']),'known':[(x.get('requested'),x.get('status')) for x in result['known_endpoint_tests']],'api_candidates':len(result['discovered_api_candidates'])},indent=2))
