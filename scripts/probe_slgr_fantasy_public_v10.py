#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
import requests
URL='https://fantasy.slgr.gr/main.dart.js'; CLASSES=['bPy','bPB','bPz','bEp','bGB','bPf']
OUT=Path('/mnt/data/nexus-slgr-fantasy-public-probe-v10');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/javascript,*/*','Referer':'https://fantasy.slgr.gr/'})
r=s.get(URL,timeout=90);r.raise_for_status();t=r.text;b=r.content
res_classes={}
for cls in CLASSES:
 constructors=[];calls=[]
 for pat in [rf'{re.escape(cls)}:function {re.escape(cls)}\(([^)]*)\)\{{',rf'function {re.escape(cls)}\(([^)]*)\)\{{']:
  for m in re.finditer(pat,t):
   constructors.append({'offset':m.start(),'args':m.group(1),'context':t[max(0,m.start()-1200):min(len(t),m.start()+5000)]})
 for m in list(re.finditer(rf'new A\.{re.escape(cls)}\(',t))[:200]:
  ctx=t[max(0,m.start()-5000):min(len(t),m.start()+7000)]
  calls.append({'offset':m.start(),'context':ctx,'strings':sorted(set(re.findall(r'\\?"([^"\\]{1,260})\\?"',ctx)))[:500]})
 res_classes[cls]={'constructors':constructors[:20],'call_sites':calls,'call_count':len(calls)}
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V10','bundle':{'url':r.url,'status':r.status_code,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()},'classes':res_classes,'governance':{'api_requests_made':False,'authenticated_surface_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'classes':{k:{'constructors':[(x['args'],x['offset']) for x in v['constructors']],'call_count':v['call_count']} for k,v in res_classes.items()}},ensure_ascii=False,indent=2))
