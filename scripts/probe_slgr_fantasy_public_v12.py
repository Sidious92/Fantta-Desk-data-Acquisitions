#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
import requests
URL='https://fantasy.slgr.gr/main.dart.js'; NEEDLE='current_players_list_id'
OUT=Path('/mnt/data/nexus-slgr-fantasy-public-probe-v12');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/javascript,*/*','Referer':'https://fantasy.slgr.gr/'})
r=s.get(URL,timeout=90);r.raise_for_status();t=r.text;b=r.content
occ=[];parser_names=set();result_classes=set()
for m in re.finditer(re.escape(NEEDLE),t):
 pos=m.start();pre=t[max(0,pos-25000):pos]
 # Dart2js top-level functions typically appear as name(a){...} or name(a,b){...}
 defs=list(re.finditer(r'(?:^|\n)([A-Za-z0-9_$]+)\(([^)]*)\)\{',pre))
 fn=defs[-1].group(1) if defs else None
 fn_start=max(0,pos-25000)+(defs[-1].start(1) if defs else 0)
 ctx=t[max(0,fn_start-1200):min(len(t),pos+12000)]
 if fn:parser_names.add(fn)
 for z in re.findall(r'return new A\.([A-Za-z0-9_$]+)\(',ctx):result_classes.add(z)
 occ.append({'offset':pos,'nearest_function':fn,'context':ctx})
# Trace parser usage and nearby network/request objects.
uses=[]
for fn in sorted(parser_names):
 for m in list(re.finditer(rf'\bA\.{re.escape(fn)}\(',t))[:200]+list(re.finditer(rf'(?<![A-Za-z0-9_$]){re.escape(fn)}\(',t))[:200]:
  pos=m.start()
  if any(abs(pos-x['offset'])<2000 for x in occ):continue
  ctx=t[max(0,pos-8000):min(len(t),pos+10000)]
  req_classes=sorted(set(re.findall(r'new A\.([A-Za-z0-9_$]+)\(',ctx)))
  paths=sorted(set(re.findall(r'\\?"(/[^"\\]{1,220})\\?"',ctx)))
  uses.append({'parser':fn,'offset':pos,'request_or_model_classes':req_classes[:250],'path_literals':paths[:200],'context':ctx})
# Trace model class constructors/usages too.
class_uses=[]
for cls in sorted(result_classes):
 for m in list(re.finditer(rf'new A\.{re.escape(cls)}\(',t))[:200]:
  pos=m.start();ctx=t[max(0,pos-6000):min(len(t),pos+7000)]
  class_uses.append({'class':cls,'offset':pos,'path_literals':sorted(set(re.findall(r'\\?"(/[^"\\]{1,220})\\?"',ctx)))[:150],'context':ctx})
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V12','bundle':{'url':r.url,'status':r.status_code,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()},'needle':NEEDLE,'occurrences':occ,'parser_names':sorted(parser_names),'result_classes':sorted(result_classes),'parser_uses':uses,'result_class_uses':class_uses,'governance':{'api_requests_made':False,'authenticated_surface_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'parser_names':sorted(parser_names),'result_classes':sorted(result_classes),'parser_use_count':len(uses),'class_use_count':len(class_uses),'uses_compact':[{'parser':x['parser'],'offset':x['offset'],'classes':x['request_or_model_classes'][:30],'paths':x['path_literals'][:30]} for x in uses[:50]]},ensure_ascii=False,indent=2))
