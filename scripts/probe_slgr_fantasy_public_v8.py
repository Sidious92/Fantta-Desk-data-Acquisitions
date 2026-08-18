#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
import requests
URL='https://fantasy.slgr.gr/main.dart.js'
OUT=Path('/mnt/data/nexus-slgr-fantasy-public-probe-v8');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/javascript,*/*','Referer':'https://fantasy.slgr.gr/'})
r=s.get(URL,timeout=90);r.raise_for_status();t=r.text;b=r.content
items=[]
for m in re.finditer(r'A\.([A-Za-z0-9_$]+)\.prototype=\{',t):
 cls=m.group(1);start=m.start();end=t.find('\nA.',m.end())
 if end<0 or end-start>40000:end=min(len(t),start+40000)
 block=t[start:end]
 if 'gaJ(a)' not in block:continue
 gm=re.search(r'gaJ\(a\)\{(.{0,5000}?)\}(?:,|\n)',block,re.S)
 if not gm:continue
 gj=gm.group(1)
 qm=re.search(r'gbD\(\)\{(.{0,7000}?)\}(?:,|\n)',block,re.S)
 query=qm.group(1) if qm else None
 strings=sorted(set(re.findall(r'\\?"([^"\\]{1,260})\\?"',gj+(query or ''))))
 qkeys=sorted(set(re.findall(r'\.n\(0,\\?"([^"\\]+)\\?"',query or '')))
 items.append({'class':cls,'gaJ_body':gj,'gbD_body':query,'string_literals':strings,'query_keys':qkeys})
uniq=[];seen=set()
for x in items:
 k=(x['gaJ_body'],x['gbD_body'])
 if k in seen:continue
 seen.add(k);uniq.append(x)
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V8','bundle':{'url':r.url,'status':r.status_code,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()},'api_base':'https://fantaking-api.dunkest.com/api/v1','request_contract_count':len(uniq),'request_contracts':uniq,'governance':{'api_requests_made':False,'authenticated_surface_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
# Compact console inventory, excluding obviously mutating/private routes only from print, not from persisted evidence.
print(json.dumps({'contracts':len(uniq),'paths':[{'class':x['class'],'gaJ':x['gaJ_body'],'query_keys':x['query_keys']} for x in uniq]},ensure_ascii=False,indent=2))
