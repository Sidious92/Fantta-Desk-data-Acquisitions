#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,re
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path

OUT=Path('data/nexus-d1/final-v2')

def now(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def sha(b:bytes): return hashlib.sha256(b).hexdigest()
def load(p):
    b=Path(p).read_bytes(); return json.loads(b), {'path':str(p),'size':len(b),'sha256':sha(b)}
def key(kind, value): return f"nexus-{kind}-v2-{sha((kind+'|'+str(value)).encode())[:24]}"
def sid(r):
    s=r.get('subjectId')
    if s is not None:return str(s)
    x=r.get('fantacalcioPlayerId') or r.get('playerId') or r.get('understatPlayerId')
    return str(x) if x is not None else None
def bridge(r):
    b=r.get('bridgePersonKey')
    if b:return str(b)
    u=r.get('understatPlayerId')
    if u:return f'understat:{u}'
    s=sid(r) or ''
    m=re.fullmatch(r'historical-understat-(\d+)',s)
    return f'understat:{m.group(1)}' if m else None
def fc_current_id(r):
    for k in ('fantacalcioPlayerId','fantacalcioSourcePlayerId','fantacalcioId','playerId','sourcePlayerId','sourceIdentityId'):
        v=r.get(k)
        if v is not None and str(v).isdigit():return str(v)
    s=sid(r) or '';m=re.fullmatch(r'current-fc-(\d+)',s);return m.group(1) if m else None
def name_of(r):
    for k in ('fullName','canonicalName','lookupName','sourceName','name'):
        if r.get(k):return str(r[k])
    xs=r.get('lookupNames') or []
    return str(xs[0]) if xs else None
def qid(r):
    q=r.get('wikidataItemId'); return str(q) if q else None
def dedupe_dicts(xs):
    seen=set();out=[]
    for x in xs:
        k=json.dumps(x,sort_keys=True,ensure_ascii=False)
        if k not in seen:seen.add(k);out.append(x)
    return out

def dob_iso(v):
    """Normalize only explicit day-precision DOB evidence; never infer a date."""
    if isinstance(v,str):
        m=re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})',v)
        if m:return v
        m=re.fullmatch(r'\+?(\d{4})-(\d{2})-(\d{2})T[^ ]+',v)
        if m:return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    if isinstance(v,dict):
        if v.get('precision') != 11:
            raise RuntimeError(f'NON_DAY_PRECISION_DOB:{json.dumps(v,sort_keys=True)}')
        t=v.get('time')
        if isinstance(t,str):
            m=re.fullmatch(r'\+?(\d{4})-(\d{2})-(\d{2})T[^ ]+',t)
            if m:return f'{m.group(1)}-{m.group(2)}-{m.group(3)}'
    raise RuntimeError(f'UNSUPPORTED_DOB_REPRESENTATION:{json.dumps(v,sort_keys=True,default=str)}')

current,mc=load('.nexus-d1-current-505-wikidata-v2-1-status/RESULT.json')
hist,mh=load('.nexus-d1-historical-2048-wikidata-v4-1-status/RESULT.json')
sp,msp=load('data/nexus-d1/second-pass-v2/SECOND_PASS_SUBJECTS.json')
cur2,mcur2=load('data/nexus-d1/current-open-fantacalcio-v2/RESULT.json')
hopen,mhopen=load('data/nexus-d1/historical-open-fantacalcio-v2/RESULT.json')
hconf,mhconf=load('data/nexus-d1/historical-dob-conflict-fantacalcio-v1/RESULT.json')
resid,mresid=load('data/nexus-d1/historical-residual-review-v1/RESULT.json')
g445,mg445=load('data/nexus-d1/historical-445-demographic-cluster-audit-v1/RESULT.json')
o445,mo445=load('.nexus-d1-historical-445-observation-demographics-v1-status/RESULT.json')
retry,mretry=load('data/nexus-d1/historical-445-single-retry-v1/RESULT.json')
preserve,mpreserve=load('.nexus-d1-secondary-raw-preservation-v2-status/RESULT.json')

assert current['status']=='PASS' and current['summary']['subjects']==505 and current['summary']['requestFailures']==0
assert hist['status']=='PASS' and hist['summary']['subjects']==2048 and hist['summary']['requestFailures']==0
assert sp['status']=='PASS' and sp['scope']['currentOpenRecords']==127 and sp['scope']['historicalOpenRecords']==155
assert cur2['status']=='PASS' and cur2['summary']['currentIdentityDobVerified']==127
assert hopen['status']=='PASS' and resid['status']=='PASS' and hconf['status']=='PASS'
assert g445['status']=='PASS' and g445['summary']['groups']==445
assert o445['status']=='PASS' and o445['summary']['observations']==704
assert retry['status']=='PASS'
assert preserve['status']=='PASS' and preserve['rules']['preservationReplayOnly'] is True
cr=current.get('records') or []; hr=hist.get('records') or []
assert len(cr)==505 and len(hr)==2048

cur_open_meta={str(r['subjectId']):r for r in sp['currentOpen']}
cur_override={str(r['subjectId']):r for r in cur2['records']}
assert len(cur_override)==127

hist_person_key={}
hist_qid_to_keys=defaultdict(set)
for r in hr:
    b=bridge(r)
    if not b: raise RuntimeError(f'HISTORICAL_WITHOUT_D0_BRIDGE:{sid(r)}')
    pk=key('person',b); hist_person_key[sid(r)]=pk
    if r.get('mappingStatus')=='IDENTITY_VERIFIED' and qid(r): hist_qid_to_keys[qid(r)].add(pk)
unique_qid_key={q:next(iter(v)) for q,v in hist_qid_to_keys.items() if len(v)==1}

hist_override={}
for r in hopen['records']:
    if r.get('dateOfBirth'): hist_override[str(r['subjectId'])]={'dateOfBirth':dob_iso(r['dateOfBirth']),'status':'DOB_VERIFIED','method':'EXACT_FC_OBSERVATION_WITH_D0_BRIDGE'}
for r in resid['historicalOpenResiduals']:
    if r.get('dateOfBirth'): hist_override[str(r['subjectId'])]={'dateOfBirth':dob_iso(r['dateOfBirth']),'status':'DOB_VERIFIED','method':'EXACT_FC_CONSENSUS_WITH_D0_BRIDGE'}
for r in hconf['records']:
    if r.get('dateOfBirth'): hist_override[str(r['subjectId'])]={'dateOfBirth':dob_iso(r['dateOfBirth']),'status':'DOB_VERIFIED','method':'DOB_CONFLICT_RESOLVED_BY_EXACT_FC_OBSERVATION'}
for r in resid['historicalDobConflictResiduals']:
    if r.get('dateOfBirth'):
        hist_override[str(r['subjectId'])]={'dateOfBirth':dob_iso(r['dateOfBirth']),'status':'DOB_VERIFIED','method':'DOB_CONFLICT_RESOLVED_BY_EXACT_FC_CONSENSUS'}
    else:
        hist_override[str(r['subjectId'])]={'dateOfBirth':None,'status':'DOB_CONFLICT','method':'SOURCE_CONFLICT_UNRESOLVED','candidateDates':sorted(set((r.get('existingConflictDates') or [])+(r.get('exactFantacalcioDobValues') or [])))}

persons={}
def add_person(pk, scope, subject_id, dobrec, aliases, observed_name, identity_method, source_status):
    p=persons.setdefault(pk,{'personKey':pk,'scopes':[],'subjectRefs':[],'providerAliases':[],'observedNames':[],'demographicsEvidence':[]})
    if scope not in p['scopes']:p['scopes'].append(scope)
    p['subjectRefs'].append({'scope':scope,'subjectId':subject_id,'identityMethod':identity_method,'sourceIdentityStatus':source_status})
    p['providerAliases'].extend(aliases)
    if observed_name and observed_name not in p['observedNames']:p['observedNames'].append(observed_name)
    p['demographicsEvidence'].append({'scope':scope,'subjectId':subject_id,**dobrec})

hist_verified=0;hist_conflict=0
for r in hr:
    s=sid(r); pk=hist_person_key[s]
    if s in hist_override: d=hist_override[s]
    elif r.get('dateOfBirthStatus')=='DOB_VERIFIED' and r.get('dateOfBirth'):
        d={'dateOfBirth':dob_iso(r['dateOfBirth']),'status':'DOB_VERIFIED','method':'WIKIDATA_FIRST_PASS_DAY_PRECISION'}
    else: raise RuntimeError(f'HISTORICAL_FINAL_DOB_UNACCOUNTED:{s}:{r.get("dateOfBirthStatus")}')
    hist_verified += d['status']=='DOB_VERIFIED'; hist_conflict += d['status']=='DOB_CONFLICT'
    aliases=[{'provider':'Understat','providerId':bridge(r).split(':',1)[1],'scope':'PERSON_BRIDGE_D0'}]
    if qid(r):aliases.append({'provider':'Wikidata','providerId':qid(r),'scope':'ENTITY'})
    add_person(pk,'HISTORICAL_2015_16_2025_26',s,d,aliases,name_of(r),'D0_UNDERSTAT_PERSON_BRIDGE',r.get('mappingStatus'))
assert hist_verified==2047 and hist_conflict==1

cur_verified=0
for r in cr:
    s=sid(r); extra=cur_open_meta.get(s,{})
    merged=dict(r); merged.update({k:v for k,v in extra.items() if v is not None})
    if s in cur_override:
        rr=cur_override[s]; d={'dateOfBirth':dob_iso(rr['dateOfBirth']),'status':'DOB_VERIFIED','method':'CURRENT_LISTONE_EXACT_FANTACALCIO_ID'}; nm=rr.get('fullName') or name_of(merged)
    elif r.get('dateOfBirthStatus')=='DOB_VERIFIED' and r.get('dateOfBirth'):
        d={'dateOfBirth':dob_iso(r['dateOfBirth']),'status':'DOB_VERIFIED','method':'WIKIDATA_FIRST_PASS_DAY_PRECISION'}; nm=name_of(merged)
    else: raise RuntimeError(f'CURRENT_FINAL_DOB_UNACCOUNTED:{s}:{r.get("dateOfBirthStatus")}')
    b=bridge(merged); q=qid(merged)
    if b:
        pk=key('person',b); ident='EXACT_D0_UNDERSTAT_BRIDGE'
    elif q and q in unique_qid_key:
        pk=unique_qid_key[q]; ident='EXACT_VERIFIED_WIKIDATA_QID_TO_HISTORICAL_PERSON'
    elif q and merged.get('mappingStatus')=='IDENTITY_VERIFIED':
        pk=key('person-qid',q); ident='EXACT_VERIFIED_WIKIDATA_QID'
    else:
        pk=key('person-current',s); ident='CURRENT_LISTONE_EXACT_PROVIDER_OBSERVATION'
    aliases=[];fc=fc_current_id(merged)
    if fc:aliases.append({'provider':'Fantacalcio','providerId':fc,'scope':'CURRENT_LISTONE_2026_27'})
    if b:aliases.append({'provider':'Understat','providerId':b.split(':',1)[1],'scope':'PERSON_BRIDGE_D0'})
    if q:aliases.append({'provider':'Wikidata','providerId':q,'scope':'ENTITY'})
    add_person(pk,'CURRENT_2026_27',s,d,aliases,nm,ident,'IDENTITY_VERIFIED')
    cur_verified+=1
assert cur_verified==505

for p in persons.values():
    p['providerAliases']=dedupe_dicts(p['providerAliases']);p['subjectRefs']=dedupe_dicts(p['subjectRefs']);p['demographicsEvidence']=dedupe_dicts(p['demographicsEvidence'])
    verified={dob_iso(x['dateOfBirth']) for x in p['demographicsEvidence'] if x['status']=='DOB_VERIFIED' and x.get('dateOfBirth')}
    has_conflict=any(x['status']=='DOB_CONFLICT' for x in p['demographicsEvidence'])
    if len(verified)>1: raise RuntimeError(f'CROSS_SCOPE_VERIFIED_DOB_CONFLICT:{p["personKey"]}:{sorted(verified)}')
    if has_conflict:
        p['dateOfBirthStatus']='DOB_CONFLICT';p['dateOfBirth']=None
    elif len(verified)==1:
        p['dateOfBirthStatus']='DOB_VERIFIED';p['dateOfBirth']=next(iter(verified))
    else: raise RuntimeError(f'PERSON_WITHOUT_DOB_EVIDENCE:{p["personKey"]}')
    p['globalPersonPromotionGranted']=True

units=[]
for g in g445['groups']:
    idx=g['sourceSubjectIndex'];fc=str(g['fantacalcioPlayerId']);sigs=g.get('signatures') or []
    dobs=sorted({dob_iso(x.get('dateOfBirth')) for x in sigs if x.get('dateOfBirth')})
    if len(dobs)!=1: raise RuntimeError(f'PROVIDER_SCOPED_GROUP_WITHOUT_SINGLE_DOB_CONSENSUS:{idx}:{dobs}')
    st='PROVIDER_SCOPED_SINGLE_DEMOGRAPHIC_SIGNATURE' if g['status']=='SINGLE_EXACT_DEMOGRAPHIC_SIGNATURE' else 'PROVIDER_SCOPED_MULTIPLE_NAME_SIGNATURES_SAME_DOB'
    units.append({'identityUnitKey':key('provider-unit',f'fantacalcio|historical-audit-group|{idx}|{fc}'),'provider':'Fantacalcio','providerId':fc,'sourceSubjectIndex':idx,'status':st,'dateOfBirthStatus':'DOB_VERIFIED','dateOfBirth':dobs[0],'demographicSignatures':sigs,'observationCount':g['observationCount'],'verifiedObservationCount':g['verifiedObservationCount'],'failedObservationCount':g['failedObservationCount'],'providerIdReuseOrNameVariationFlag':g['providerIdReuseOrNameVariationFlag'],'globalPersonPromotionGranted':False,'personMergePerformed':False})
assert len(units)==445

unresolved=[r for r in resid['historicalDobConflictResiduals'] if not r.get('dateOfBirth')]
assert len(unresolved)==1 and unresolved[0]['subjectId']=='historical-understat-4904'
failed_obs=[r for r in o445['records'] if r.get('status')!='OBSERVATION_DEMOGRAPHICS_VERIFIED']
assert len(failed_obs)==1 and failed_obs[0]['fantacalcioPlayerId']=='61' and failed_obs[0]['season']=='2015/16'
multi=[u for u in units if u['status']=='PROVIDER_SCOPED_MULTIPLE_NAME_SIGNATURES_SAME_DOB']
assert len(multi)==2 and {u['providerId'] for u in multi}=={'6024','6164'}

captured=now(); person_list=sorted(persons.values(),key=lambda x:x['personKey']);units=sorted(units,key=lambda x:x['identityUnitKey'])
master={'schema':'NEXUS_D1_IDENTITY_MASTER_V2','protocolVersion':'1.1','status':'PASS','capturedAt':captured,'scope':{'currentSubjectRecords':505,'historicalUnderstatSubjectRecords':2048,'uniqueGlobalPersonKeys':len(person_list),'historicalProviderScopedIdentityUnits':445},'rules':{'internalPersonKeyDistinctFromProviderIds':True,'providerIdsUsedAsGlobalPersonKeys':False,'historicalD0UnderstatBridgeIsIdentityAuthority':True,'currentExactFantacalcioIdIsCurrentObservationKeyOnly':True,'historicalUnbridgedFantacalcioUnitsRemainProviderScoped':True,'wikidataStatementDobNormalizedOnlyAtDayPrecision':True,'nameOnlyMergeUsed':False,'fuzzyMatchingUsed':False,'dobInferred':False,'computedAgeDerived':False,'historicalAsOfGrantedByCurrentRetrieval':False,'trainingPromotionGranted':False,'f1Started':False,'d2Started':False},'persons':person_list,'providerScopedIdentityUnits':units}

registry={'schema':'NEXUS_D1_REGISTRY_V2','protocolVersion':'1.1','status':'D1_READY_FOR_FINAL_IMMUTABLE_FREEZE','capturedAt':captured,'counts':{'current':{'subjects':505,'dobVerified':505,'dobConflict':0},'historicalUnderstatBacked':{'subjects':2048,'dobVerified':2047,'dobConflict':1},'historicalNeverUnderstatBridged':{'providerScopedGroups':445,'singleDemographicSignature':443,'multipleNameSignaturesSameDob':2,'groupsWithoutDobConsensus':0,'providerObservations':704,'verifiedObservations':703,'sourceNoCoverageOrBindingFailedObservations':1},'identityMaster':{'uniqueGlobalPersonKeys':len(person_list),'providerScopedIdentityUnits':445}},'typedResiduals':{'dobConflicts':[{'subjectId':unresolved[0]['subjectId'],'understatPlayerId':unresolved[0]['understatPlayerId'],'wikidataItemId':unresolved[0]['wikidataItemId'],'candidateDates':sorted(set((unresolved[0].get('existingConflictDates') or [])+(unresolved[0].get('exactFantacalcioDobValues') or []))),'missingReason':'DOB_CONFLICT'}],'providerScopedMultipleNameSignatureGroups':[{'identityUnitKey':u['identityUnitKey'],'fantacalcioPlayerId':u['providerId'],'dateOfBirth':u['dateOfBirth'],'status':u['status']} for u in multi],'sourceCoverageGaps':[{'provider':'Fantacalcio','fantacalcioPlayerId':'61','season':'2015/16','observedName':failed_obs[0].get('observedName'),'missingReason':'SOURCE_NO_COVERAGE','groupStillHasVerifiedDobSignature':True}]},'governance':master['rules'],'rawPreservation':{'currentFirstPassRelease':'nexus-d1-current-505-wikidata-v2-1','historicalFirstPassRelease':'nexus-d1-historical-2048-wikidata-v4-1','historical445ObservationRawRelease':'nexus-d1-historical-445-observation-demographics-v1','secondaryRawPreservationRelease':'nexus-d1-secondary-raw-preservation-v2'},'nextAllowedAction':'D1_FINAL_IMMUTABLE_FREEZE','d2Allowed':False}

OUT.mkdir(parents=True,exist_ok=True)
mb=(json.dumps(master,ensure_ascii=False,indent=2)+'\n').encode();rb=(json.dumps(registry,ensure_ascii=False,indent=2)+'\n').encode();(OUT/'IDENTITY_MASTER.json').write_bytes(mb);(OUT/'D1_REGISTRY.json').write_bytes(rb)
sources=[mc,mh,msp,mcur2,mhopen,mhconf,mresid,mg445,mo445,mretry,mpreserve]
manifest={'schema':'NEXUS_D1_FINAL_PACKAGE_MANIFEST_V2','protocolVersion':'1.1','status':'PASS','generatedAt':captured,'outputs':{'identityMaster':{'path':'IDENTITY_MASTER.json','size':len(mb),'sha256':sha(mb)},'registry':{'path':'D1_REGISTRY.json','size':len(rb),'sha256':sha(rb)}},'sourceAuthorities':sources,'governance':master['rules']}
(OUT/'MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'status':'PASS','currentDob':'505/505','historicalUnderstatDob':'2047/2048','historicalDobConflict':1,'providerScopedGroups':445,'uniqueGlobalPersonKeys':len(person_list)},indent=2))
