#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
OUT=Path('/mnt/data/nexus-fotmob-player-page-probe-v2');OUT.mkdir(parents=True,exist_ok=True)
PLAYERS=[
 ('Matija Frigan',1190371,'matija-frigan'),
 ('Andrea Adorante',1024432,'andrea-adorante'),
 ('Kornel Lisman',1529483,'kornel-lisman'),
 ('Albion Rrahmani',1379468,'albion-rrahmani')
]
H={'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/javascript,application/json,*/*'}
def sha(b):return hashlib.sha256(b).hexdigest()
rows=[]
for name,pid,slug in PLAYERS:
 url=f'https://www.fotmob.com/players/{pid}/{slug}'
 r=requests.get(url,headers=H,timeout=(8,30),allow_redirects=True);b=r.content;t=r.text
 rec={'name':name,'id':pid,'url':r.url,'status':r.status_code,'bytes':len(b),'sha256':sha(b),'content_type':r.headers.get('content-type','')}
 # Exact script payloads declared by page.
 scripts=[]
 for m in re.finditer(r'<script([^>]*)>(.*?)</script>',t,re.I|re.S):
  attrs,body=m.group(1),m.group(2)
  srcm=re.search(r'src=["\']([^"\']+)',attrs,re.I)
  typem=re.search(r'type=["\']([^"\']+)',attrs,re.I)
  if srcm:
   scripts.append({'src':urljoin(r.url,srcm.group(1)),'type':typem.group(1) if typem else None})
  elif body.strip() and any(k in body.lower() for k in ['player','season','career','stat','league','goal','match']):
   scripts.append({'inline':body[:200000],'type':typem.group(1) if typem else None})
 # Keyword contexts from HTML/React flight payload.
 contexts={}
 for needle in ['statSeasons','careerHistory','career','season','league','playerData','player-data','goals','matches','tournament','__NEXT_DATA__','self.__next_f.push']:
  hits=[]
  for z in list(re.finditer(re.escape(needle),t,re.I))[:80]:hits.append(t[max(0,z.start()-1200):min(len(t),z.start()+3000)])
  if hits:contexts[needle]=hits
 rec['scripts']=scripts[:200];rec['contexts']=contexts
 # Explicit URL/API strings already embedded in official page only.
 urls=sorted(set(re.findall(r'https?://[^"\'\\\s<>]+',t)))
 rec['embedded_urls']=[u for u in urls if any(k in u.lower() for k in ['api','fotmob','player','stats'])][:500]
 rows.append(rec)
res={'schema':'NEXUS_FOTMOB_PUBLIC_PLAYER_PAGE_PAYLOAD_PROBE_V2','players':rows,'governance':{'only_public_player_pages_requested':True,'authenticated_surface_accessed':False,'private_routes_accessed':False,'api_endpoint_guessing_used':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'players':[(x['name'],x['status'],x['bytes'],list(x['contexts'].keys()),len(x['scripts']),len(x['embedded_urls'])) for x in rows]},ensure_ascii=False,indent=2))
