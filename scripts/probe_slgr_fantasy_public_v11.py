#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from pathlib import Path
import requests
URL='https://fantasy.slgr.gr/main.dart.js'
OUT=Path('/mnt/data/nexus-slgr-fantasy-public-probe-v11');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'application/javascript,*/*','Referer':'https://fantasy.slgr.gr/'})
r=s.get(URL,timeout=90);r.raise_for_status();t=r.text;b=r.content
# Locate roster constructor calls and infer enclosing prototype/method.
roster=[]
for m in re.finditer(r'new A\.bPy\(',t):
 pos=m.start();pre=t[max(0,pos-80000):pos]
 prot=list(re.finditer(r'A\.([A-Za-z0-9_$]+)\.prototype=\{',pre))
 owner=prot[-1].group(1) if prot else None
 owner_start=max(0,pos-80000)+(prot[-1].start() if prot else 0)
 method_pre=t[owner_start:pos]
 methods=list(re.finditer(r'(?:^|[},\n])([A-Za-z0-9_$]+)\([^)]*\)\{',method_pre))
 method=methods[-1].group(1) if methods else None
 ctx=t[max(0,pos-12000):min(len(t),pos+9000)]
 roster.append({'offset':pos,'owner_prototype':owner,'enclosing_method':method,'context':ctx})
# Trace direct textual call sites for the observed enclosing method(s).
method_names=sorted({x['enclosing_method'] for x in roster if x['enclosing_method']})
method_calls=[]
for name in method_names:
 for pat in [rf'\.{re.escape(name)}\(',rf'\b{re.escape(name)}\(']:
  for m in list(re.finditer(pat,t))[:300]:
   if any(abs(m.start()-x['offset'])<50 for x in roster):continue
   ctx=t[max(0,m.start()-7000):min(len(t),m.start()+9000)]
   method_calls.append({'method':name,'offset':m.start(),'match':m.group(0),'context':ctx,'new_objects':sorted(set(re.findall(r'new A\.([A-Za-z0-9_$]+)\(',ctx)))[:200]})
# Search for constructors whose instances near call sites carry the known request-action shape through five+ args.
action_candidates=[]
for c in method_calls:
 ctx=c['context']
 for m in re.finditer(r'new A\.([A-Za-z0-9_$]+)\(([^\n;]{1,500})\)',ctx):
  args=m.group(2)
  if args.count(',')>=4:
   action_candidates.append({'method':c['method'],'call_offset':c['offset'],'class':m.group(1),'args':args[:500],'context':ctx[max(0,m.start()-1200):min(len(ctx),m.end()+1800)]})
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V11','bundle':{'url':r.url,'status':r.status_code,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()},'roster_constructor_calls':roster,'enclosing_methods':method_names,'method_call_sites':method_calls,'action_candidates':action_candidates[:1000],'governance':{'api_requests_made':False,'authenticated_surface_accessed':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'roster_calls':[(x['offset'],x['owner_prototype'],x['enclosing_method']) for x in roster],'method_names':method_names,'method_call_count':len(method_calls),'action_candidates':[(x['class'],x['args']) for x in action_candidates[:100]]},ensure_ascii=False,indent=2))
