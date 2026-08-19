#!/usr/bin/env python3
from __future__ import annotations

import hashlib,json,re
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from urllib.parse import urljoin
import requests

PAGE='https://fantasy.proleague.be/stats'
OUT=Path('/mnt/data/nexus-belgian-historical-contract-v1');OUT.mkdir(parents=True,exist_ok=True)
HEADERS={'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/javascript,*/*'}
TERMS=['seasonId','competitionFeed','players_JPL_','spelers_JPL_','players-stats','points-confirmation','season','history']

def sha(b):return hashlib.sha256(b).hexdigest()
def get(u):return requests.get(u,headers=HEADERS,timeout=(8,30),allow_redirects=True)

page=get(PAGE);page.raise_for_status();html=page.text
srcs=list(dict.fromkeys(urljoin(page.url,x) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I)))

def scan(url):
 try:
  r=get(url)
  if r.status_code!=200:return None
  text=r.text;contexts=[];ids=set();urls=set();routes=set()
  for term in TERMS:
   for m in list(re.finditer(re.escape(term),text,re.I))[:120]:
    ctx=text[max(0,m.start()-1800):min(len(text),m.start()+3200)]
    # Capture explicit seasonId literals only when syntactically near seasonId.
    for mm in re.finditer(r'seasonId.{0,120}?([12][0-9]{3})',ctx,re.I|re.S): ids.add(int(mm.group(1)))
    for mm in re.finditer(r'([12][0-9]{3}).{0,120}?seasonId',ctx,re.I|re.S): ids.add(int(mm.group(1)))
    for val in re.findall(r'https?://[^"\'`\\\s]{5,300}',ctx):
     if any(k in val for k in ['fanarena','proleague.code.brussels','fantasy.proleague']):urls.add(val)
    for val in re.findall(r'["\'`](/[^"\'`\\]{1,250})["\'`]',ctx):
     if any(k in val.lower() for k in ['season','player','point','club','match']):routes.add(val)
    contexts.append({'term':term,'context':ctx})
  if not contexts:return None
  return {'url':r.url,'bytes':len(r.content),'sha256':sha(r.content),'season_id_literals':sorted(ids),'provider_urls':sorted(urls),'route_candidates':sorted(routes),'contexts':contexts[:200]}
 except Exception as e:return {'url':url,'error':repr(e),'season_id_literals':[],'provider_urls':[],'route_candidates':[],'contexts':[]}

hits=[]
with ThreadPoolExecutor(max_workers=8) as ex:
 futs=[ex.submit(scan,u) for u in srcs]
 for fut in as_completed(futs):
  x=fut.result()
  if x:hits.append(x)
ids=sorted(set(i for h in hits for i in h.get('season_id_literals',[])))
urls=sorted(set(u for h in hits for u in h.get('provider_urls',[])))
routes=sorted(set(u for h in hits for u in h.get('route_candidates',[])))
result={'schema':'NEXUS_BELGIAN_HISTORICAL_FANTASY_CONTRACT_PROBE_V1','status':'PASS_DISCOVERY' if hits else 'FAIL_CLOSED_DISCOVERY','page':{'url':page.url,'status':page.status_code,'bytes':len(page.content),'sha256':sha(page.content)},'script_count':len(srcs),'hit_files':len(hits),'observed_season_id_literals':ids,'provider_urls':urls,'route_candidates':routes,'hits':hits,'governance':{'public_frontend_assets_only':True,'season_ids_called':False,'season_ids_guessed':False,'authenticated_surface_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':result['status'],'scripts':len(srcs),'hit_files':len(hits),'observed_season_id_literals':ids,'provider_urls':urls[:50],'route_candidates':routes[:100]},ensure_ascii=False,indent=2))
