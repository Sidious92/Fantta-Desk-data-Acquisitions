#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from collections import deque,defaultdict
from pathlib import Path
from urllib.parse import urljoin
import requests
ORIGIN='https://ligue1.com'
PAGES=['/en/fantasy','/en/fantasy/mercato','/en/fantasy/ranking','/en/fantasy/rules','/en/fantasy/captain','/en/fantasy/line-up','/en/fantasy/my-team']
OUT=Path('/mnt/data/nexus-ligue1-official-fantasy-api-probe-v8');OUT.mkdir(parents=True,exist_ok=True)
s=requests.Session();s.headers.update({'User-Agent':'Mozilla/5.0 FantaNexus research acquisition','Accept':'text/html,application/javascript,*/*'})
def sha(b):return hashlib.sha256(b).hexdigest()
def chunk_url(base,ref):
 if ref.startswith('http://') or ref.startswith('https://'):return ref
 if ref.startswith('/'):return urljoin(ORIGIN,ref)
 if ref.startswith('static/chunks/'):return urljoin(ORIGIN,'/_next/'+ref)
 return urljoin(base,ref)
def extract_chunk_refs(txt):
 out=set()
 for pat in [r'["\'](static/chunks/[^"\']+\.js)["\']',r'["\'](/_next/static/chunks/[^"\']+\.js)["\']']:
  out.update(re.findall(pat,txt))
 return out
page_meta=[];seed_owners=defaultdict(set);errors=[]
for p in PAGES:
 try:
  r=s.get(ORIGIN+p,timeout=40,allow_redirects=True);b=r.content
  page_meta.append({'path':p,'url':r.url,'status':r.status_code,'bytes':len(b),'sha256':sha(b)})
  if r.status_code!=200:continue
  for src in re.findall(r'<script[^>]+src=["\']([^"\']+)',r.text,re.I):seed_owners[urljoin(r.url,src)].add(p)
 except Exception as e:errors.append({'page':p,'error':repr(e)})
# Crawl only JS chunks reachable from page-declared scripts, bounded fail-closed.
MAX_FILES=500;MAX_DEPTH=5
q=deque((u,0,set(pages)) for u,pages in seed_owners.items());seen={};parents=defaultdict(set);page_reach=defaultdict(set)
while q and len(seen)<MAX_FILES:
 u,depth,pages=q.popleft()
 page_reach[u].update(pages)
 if u in seen:continue
 try:
  r=s.get(u,timeout=45);r.raise_for_status();t=r.text
  if 'javascript' not in r.headers.get('content-type','').lower() and not u.endswith('.js'):continue
  refs=extract_chunk_refs(t)
  seen[u]={'url':r.url,'depth':depth,'bytes':len(r.content),'sha256':sha(r.content),'text':t,'refs':sorted(refs)}
  if depth<MAX_DEPTH:
   for ref in refs:
    cu=chunk_url(r.url,ref);parents[cu].add(u);q.append((cu,depth+1,set(page_reach[u])))
 except Exception as e:errors.append({'script':u,'depth':depth,'error':repr(e)})
# Propagate page provenance through the discovered dependency graph until stable.
changed=True
while changed:
 changed=False
 for child,pars in parents.items():
  before=len(page_reach[child])
  for p in pars:page_reach[child].update(page_reach[p])
  if len(page_reach[child])>before:changed=True
# Extract only exact API-client call sites; apiFantasyClient is exported by module 820203 and may be imported under a minified alias.
call_sites=[];auth_markers=['useAuthenticatedQuery','/api/auth/login','isUserAuthenticated','Authorization=`Bearer','coach/championship','/profile','/user/me']
for u,x in seen.items():
 t=x['text']
 # Locate module imports of 820203 and infer local alias, e.g. n=e.i(820203)
 aliases=set(re.findall(r'([A-Za-z_$][\w$]*)\s*=\s*[A-Za-z_$][\w$]*\.i\(820203\)',t))
 # Also explicit global symbol in readable builds.
 aliases.add('apiFantasyClient')
 for alias in sorted(aliases):
  # Calls like alias.apiFantasyClient.get('/path') or direct apiFantasyClient.get('/path')
  patterns=[
   (rf'{re.escape(alias)}\.apiFantasyClient\.(get|post|put|delete)\(([^\n;]{{1,500}})', 'module_export'),
   (rf'\bapiFantasyClient\.(get|post|put|delete)\(([^\n;]{{1,500}})', 'direct')
  ]
  for pat,kind in patterns:
   for m in re.finditer(pat,t):
    method=m.group(1).upper();arg=m.group(2)
    pos=m.start();ctx=t[max(0,pos-2200):min(len(t),pos+2600)]
    lits=re.findall(r'["\']([^"\']{1,260})["\']',arg)
    tmpls=re.findall(r'`([^`]{1,260})`',arg)
    route_candidates=[]
    for z in lits+tmpls:
     if z.startswith('/') or any(k in z.lower() for k in ['championship','player','club','gameweek','ranking','season','coach','asset']):route_candidates.append(z)
    auth_hits=sorted(k for k in auth_markers if k in ctx)
    call_sites.append({'url':u,'pages':sorted(page_reach[u]),'depth':x['depth'],'sha256':x['sha256'],'alias':alias,'kind':kind,'method':method,'argument_excerpt':arg[:500],'route_candidates':sorted(set(route_candidates)),'auth_context_markers':auth_hits,'context':ctx})
# Extra fallback: within chunks importing 820203, capture .apiFantasyClient property contexts even if parser shape changed.
for u,x in seen.items():
 t=x['text']
 if '820203' not in t or 'apiFantasyClient' not in t:continue
 for m in re.finditer('apiFantasyClient',t):
  pos=m.start();ctx=t[max(0,pos-2000):min(len(t),pos+3500)]
  if any(c['url']==u and c['context']==ctx for c in call_sites):continue
  call_sites.append({'url':u,'pages':sorted(page_reach[u]),'depth':x['depth'],'sha256':x['sha256'],'alias':None,'kind':'fallback_context','method':None,'argument_excerpt':None,'route_candidates':sorted(set(re.findall(r'["\'](/[^"\']{1,220})["\']',ctx))),'auth_context_markers':sorted(k for k in auth_markers if k in ctx),'context':ctx})
# Dedupe exact calls.
uniq=[];keys=set()
for c in call_sites:
 k=(c['url'],c['method'],c['argument_excerpt'],tuple(c['route_candidates']))
 if k in keys:continue
 keys.add(k);uniq.append(c)
# Classify only; do not request fantasy API endpoints in this probe.
for c in uniq:
 c['classification']='AUTH_CONTEXT' if c['auth_context_markers'] else 'PUBLIC_CONTEXT_CANDIDATE'
res={'schema':'NEXUS_LIGUE1_OFFICIAL_FANTASY_API_PUBLIC_PROBE_V8','pages':page_meta,'crawl':{'max_files':MAX_FILES,'max_depth':MAX_DEPTH,'files_scanned':len(seen),'seed_files':len(seed_owners),'discovered_edges':sum(len(x['refs']) for x in seen.values())},'api_call_sites':uniq,'public_context_candidates':[c for c in uniq if c['classification']=='PUBLIC_CONTEXT_CANDIDATE'],'auth_context_calls':[c for c in uniq if c['classification']=='AUTH_CONTEXT'],'errors':errors,'governance':{'network_calls_limited_to_public_ligue1_pages_and_frontend_declared_js_dependencies':True,'fantasy_api_endpoint_requests_made':False,'authenticated_surface_accessed':False,'private_endpoint_bypass_attempted':False,'predictive_models_modified':False,'decision_layer_started':False}}
(OUT/'RESULT.json').write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'files_scanned':len(seen),'call_sites':len(uniq),'public_candidates':[(c['method'],c['route_candidates'],c['pages']) for c in res['public_context_candidates']],'auth_calls':[(c['method'],c['route_candidates'],c['pages']) for c in res['auth_context_calls']]},ensure_ascii=False,indent=2))
