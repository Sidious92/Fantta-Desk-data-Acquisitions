#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from urllib.parse import urljoin
import requests
START='https://fantasy.bundesliga.com/'
OUT=Path('/mnt/data/nexus-bundesliga-official-fantasy-probe-v2');OUT.mkdir(parents=True,exist_ok=True)
HEADERS={'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/javascript,application/json,*/*'}
def sha(b):return hashlib.sha256(b).hexdigest()
def fetch(u,timeout=25):return requests.get(u,headers=HEADERS,timeout=(8,timeout),allow_redirects=True)
def meta(r,u):return {'requested':u,'url':r.url,'status':r.status_code,'content_type':r.headers.get('content-type',''),'bytes':len(r.content),'sha256':sha(r.content),'preview':r.text[:1200]}
r=fetch(START);r.raise_for_status();html=r.text
base_match=re.search(r'<base[^>]+href=["\']([^"\']+)',html,re.I);base_href=base_match.group(1) if base_match else None
base_url=urljoin(r.url,base_href) if base_href else r.url
scripts=[]
for src in re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I):
 scripts.append({'src':src,'resolved':urljoin(base_url,src)})
# also stylesheet/modulepreload assets may point to lazy-manifest roots
for href in re.findall(r'<link[^>]+(?:rel=["\'](?:modulepreload|preload)["\'][^>]+)?href=["\']([^"\']+\.js[^"\']*)',html,re.I):
 scripts.append({'src':href,'resolved':urljoin(base_url,href)})
seen=set();scripts=[x for x in scripts if not (x['resolved'] in seen or seen.add(x['resolved']))]
def one(x):
 try:
  rr=fetch(x['resolved']);return {'item':x,'r':rr}
 except Exception as e:return {'item':x,'error':repr(e)}
cands=set();hits=[];errors=[]
with ThreadPoolExecutor(max_workers=8) as ex:
 for fut in as_completed([ex.submit(one,x) for x in scripts]):
  q=fut.result();it=q['item']
  if q.get('error'):errors.append({**it,'error':q['error']});continue
  rr=q['r'];txt=rr.text;ct=rr.headers.get('content-type','');m=meta(rr,it['resolved']);m['declared_src']=it['src']
  if 'html' in ct.lower() or txt.lstrip().lower().startswith('<!doctype html'):
   m['asset_valid_js']=False;hits.append(m);continue
  m['asset_valid_js']=True
  for v in re.findall(r'https?://[^"\'\\\s<>]+',txt):
   if any(k in v.lower() for k in ['api','fantasy','bundesliga','dfl','neopoly']):cands.add(v[:500])
  for v in re.findall(r'["\'](/(?:api|v1|v2|fantasy|players?|clubs?|teams?|fixtures?|matchdays?|gameweeks?|stats|ranking|market)[^"\']*)["\']',txt,re.I):cands.add(v)
  contexts=[]
  for needle in ['api','graphql','baseurl','fantasy','player','marketvalue','pointsLastSeason','neopoly']:
   for z in list(re.finditer(needle,txt,re.I))[:20]:contexts.append({'needle':needle,'text':txt[max(0,z.start()-800):min(len(txt),z.start()+1800)]})
  if contexts:m['contexts']=contexts
  hits.append(m)
res={'schema':'NEXUS_BUNDESLIGA_OFFICIAL_FANTASY_PUBLIC_PROBE_V2','page':meta(r,START),'base_href':base_href,'base_url':base_url,'declared_scripts':scripts,'script_results':hits,'script_errors':errors,'api_candidates':sorted(cands)[:2000],'governance':{'authenticated_surface_accessed':False,'private_routes_accessed':False,'endpoint_dictionary_guessing':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'page':r.url,'base_href':base_href,'base_url':base_url,'scripts':len(scripts),'valid_js':sum(1 for x in hits if x.get('asset_valid_js')),'invalid_js':sum(1 for x in hits if x.get('asset_valid_js') is False),'errors':len(errors),'api_candidates':sorted(cands)[:150]},ensure_ascii=False,indent=2))
