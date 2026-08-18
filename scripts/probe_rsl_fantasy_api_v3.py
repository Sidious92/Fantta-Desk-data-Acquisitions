#!/usr/bin/env python3
import hashlib,json,re
from pathlib import Path
from urllib.parse import urljoin
import requests
SITE='https://fantasy.spl.com.sa/'
OUT=Path('/mnt/data/nexus-rsl-fantasy-api-probe-v3');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/json,text/plain,*/*','Referer':SITE})
r=s.get(SITE,timeout=30);r.raise_for_status();html=r.text
srcs=[urljoin(r.url,x) for x in re.findall(r'<script[^>]+src=["\']([^"\']+)',html,re.I)]
u=next(x for x in srcs if '/assets/index-' in x)
rr=s.get(u,timeout=40);rr.raise_for_status();txt=rr.text
# In the current minified bundle: Yn = GET wrapper, yi = POST wrapper, _w = generic write wrapper.
patterns={
 'GET_Yn_double':r'Yn\(\"([^\"]+)\"',
 'GET_Yn_single':r"Yn\('([^']+)'",
 'GET_Yn_template':r'Yn\(`([^`]+)`',
 'IU_literal':r'IU\(\"([^\"]+)\"',
 'IU_template':r'IU\(`([^`]+)`',
 'POST_yi_double':r'yi\(\"([^\"]+)\"',
 'POST_yi_template':r'yi\(`([^`]+)`'
}
found={k:sorted(set(re.findall(p,txt))) for k,p in patterns.items()}
# Also capture nearby contexts for every call to wrappers.
contexts={k:[txt[max(0,m.start()-240):m.end()+500] for m in list(re.finditer(r'\b'+re.escape(k)+r'\s*\(',txt))[:120]] for k in ['Yn','IU','yi','_w']}
# Build safe literal GET probes. Dynamic templates only if no interpolation.
routes=set(found['GET_Yn_double']+found['GET_Yn_single']+found['IU_literal'])
for v in found['GET_Yn_template']+found['IU_template']:
 if '${' not in v:routes.add(v)
blocked=('auth/','player/logout','league/','leagues/','entry/','team/','squad/','user/','admin/')
safe=[]
for route in sorted(routes):
 route=route.lstrip('/')
 if not route or any(route.startswith(b) for b in blocked):continue
 safe.append(route)
tests=[]
for route in safe:
 url=urljoin(SITE,'api/'+route)
 try:
  x=s.get(url,timeout=25,allow_redirects=True);b=x.content
  o={'route':route,'url':x.url,'status':x.status_code,'content_type':x.headers.get('content-type',''),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'preview':x.text[:1200]}
  try:
   j=x.json();o['json_type']=type(j).__name__;o['json_keys']=list(j)[:100] if isinstance(j,dict) else None;o['json_len']=len(j) if hasattr(j,'__len__') else None
  except Exception:pass
  tests.append(o)
 except Exception as e:tests.append({'route':route,'url':url,'error':repr(e)})
res={'schema':'NEXUS_RSL_FANTASY_API_PUBLIC_PROBE_V3','main_bundle':{'url':u,'bytes':len(rr.content),'sha256':hashlib.sha256(rr.content).hexdigest()},'wrapper_routes':found,'contexts':contexts,'safe_literal_get_routes':safe,'tests':tests,'successful_anonymous_reads':[x for x in tests if x.get('status')==200]}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'found':{k:len(v) for k,v in found.items()},'safe_routes':safe,'success':[(x['route'],x.get('json_keys'),x.get('json_len')) for x in res['successful_anonymous_reads']]},indent=2))
