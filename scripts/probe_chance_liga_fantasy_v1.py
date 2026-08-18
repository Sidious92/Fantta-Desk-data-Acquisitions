#!/usr/bin/env python3
import json,re,hashlib
from urllib.parse import urljoin
from pathlib import Path
import requests

BASE='https://www.chanceliga.cz/'
OUT=Path('/mnt/data/nexus-chance-liga-fantasy-probe-v1'); OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session(); s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition'})

def fetch(url):
    r=s.get(url,timeout=30,allow_redirects=True)
    b=r.content
    return r,{'requested':url,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'preview':r.text[:1500]}

res={'schema':'NEXUS_CHANCE_LIGA_FANTASY_PUBLIC_PROBE_V1','pages':{},'scripts':[],'api_candidates':[],'literal_tests':[]}
full=''
for name,path in [('fantasy','fantasy'),('fantasy_info','text/178-fantasy'),('stats','statistiky?order=15&parameter=1&season=2026&unit=1')]:
    try:
        r,x=fetch(urljoin(BASE,path));res['pages'][name]=x
        if name=='fantasy':full=r.text
    except Exception as e:res['pages'][name]={'error':repr(e)}

scripts=[]
for src in re.findall(r'<script[^>]+src=[\"\']([^\"\']+)',full,re.I): scripts.append(urljoin(BASE,src))
api=set()
for u in dict.fromkeys(scripts):
    try:
        r,x=fetch(u); txt=r.text
        for m in re.findall(r'[\"\']([^\"\']{1,250}(?:api|ajax|fantasy|player|stats)[^\"\']{0,150})[\"\']',txt,re.I):
            if not m.startswith('data:'): api.add(m)
        x['contexts']={k:[txt[max(0,m.start()-140):m.end()+260] for m in list(re.finditer(k,txt,re.I))[:10]] for k in ['api','ajax','fantasy','player','stats']}
        res['scripts'].append(x)
    except Exception as e:res['scripts'].append({'requested':u,'error':repr(e)})
res['api_candidates']=sorted(api)[:800]

# conservative literal probes only
for p in ['api/','fantasy/api/','ajax/fantasy','fantasy/players','fantasy/stats','api/fantasy','api/players']:
    try:
        r,x=fetch(urljoin(BASE,p));
        try:
            j=r.json();x['json_type']=type(j).__name__;x['json_keys']=list(j)[:50] if isinstance(j,dict) else None;x['json_len']=len(j) if hasattr(j,'__len__') else None
        except Exception:pass
        res['literal_tests'].append(x)
    except Exception as e:res['literal_tests'].append({'requested':urljoin(BASE,p),'error':repr(e)})

res['fantasy_page']={'script_count':len(scripts),'has_login':bool(re.search(r'login|přihl',full,re.I)),'player_word_count':len(re.findall(r'player|hráč',full,re.I)),'has_embedded_json':bool(re.search(r'application/json|__NEXT_DATA__|__NUXT__',full,re.I))}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'pages':{k:v.get('status') for k,v in res['pages'].items()},'scripts':len(res['scripts']),'api_candidates':len(res['api_candidates']),'tests':[(x.get('requested'),x.get('status')) for x in res['literal_tests']]},indent=2))
