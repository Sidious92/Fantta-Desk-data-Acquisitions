#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re,html as htmlmod
from pathlib import Path
import requests
OUT=Path('/mnt/data/nexus-fotmob-nextdata-career-v3');OUT.mkdir(parents=True,exist_ok=True)
PLAYERS=[
 ('Matija Frigan',1190371,'matija-frigan'),
 ('Andrea Adorante',1024432,'andrea-adorante'),
 ('Kornel Lisman',1529483,'kornel-lisman'),
 ('Albion Rrahmani',1379468,'albion-rrahmani')
]
H={'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,*/*'}
def sha(b):return hashlib.sha256(b).hexdigest()
def walk(v,path='$',hits=None):
 if hits is None:hits=[]
 if isinstance(v,dict):
  interesting=set(v).intersection({'statSeasons','firstSeasonStats','careerHistory','career','seasons','seasonName','tournaments','tournamentId','goals','matches','appearances'})
  if interesting:
   # Persist the whole local object so relationships among season/tournament/stats are not lost.
   hits.append({'path':path,'interesting_keys':sorted(interesting),'object':v})
  for k,z in v.items():
   if isinstance(z,(dict,list)):walk(z,f'{path}.{k}',hits)
 elif isinstance(v,list):
  for i,z in enumerate(v):
   if isinstance(z,(dict,list)):walk(z,f'{path}[{i}]',hits)
 return hits
rows=[]
for name,pid,slug in PLAYERS:
 url=f'https://www.fotmob.com/players/{pid}/{slug}'
 r=requests.get(url,headers=H,timeout=(8,35),allow_redirects=True);b=r.content;t=r.text
 rec={'name':name,'id':pid,'url':r.url,'status':r.status_code,'bytes':len(b),'sha256':sha(b)}
 # Classic Next DATA.
 m=re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',t,re.I|re.S)
 next_obj=None
 if m:
  raw=htmlmod.unescape(m.group(1)).strip()
  try:next_obj=json.loads(raw)
  except Exception as e:rec['next_data_error']=repr(e)
 rec['next_data_present']=next_obj is not None
 rec['next_data_hits']=walk(next_obj) if next_obj is not None else []
 # React/Next flight strings sometimes carry server payload independently of __NEXT_DATA__.
 flight=[]
 for sm in re.finditer(r'<script[^>]*>(.*?)</script>',t,re.I|re.S):
  body=htmlmod.unescape(sm.group(1))
  if 'self.__next_f.push' in body and any(k in body for k in ['statSeasons','firstSeasonStats','careerHistory']):
   flight.append(body[:500000])
 rec['flight_payload_count']=len(flight)
 rec['flight_payloads']=flight[:40]
 rows.append(rec)
res={'schema':'NEXUS_FOTMOB_PUBLIC_NEXTDATA_CAREER_PROBE_V3','players':rows,'governance':{'only_verified_public_player_pages_requested':True,'api_endpoint_guessing_used':False,'authenticated_surface_accessed':False,'private_routes_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
print(json.dumps({'players':[{'name':x['name'],'status':x['status'],'next':x['next_data_present'],'next_hits':len(x['next_data_hits']),'flight_payloads':x['flight_payload_count'],'hit_paths':[h['path'] for h in x['next_data_hits'][:20]]} for x in rows]},ensure_ascii=False,indent=2))
