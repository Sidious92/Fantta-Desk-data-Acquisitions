#!/usr/bin/env python3
"""Final D1 builder v3.

Deterministically derives v3 from the reviewed v2 builder, adding the six-record
non-day Wikidata DOB recovery authority. It never rewrites source evidence.
Internal person-key namespace remains v1 so technical builder versioning cannot
change identity keys.
"""
from pathlib import Path

p=Path('scripts/nexus-d1-build-final-identity-master-v2.py')
src=p.read_text()
repls=[
("OUT=Path('data/nexus-d1/final-v2')","OUT=Path('data/nexus-d1/final-v3')"),
("def key(kind, value): return f\"nexus-{kind}-v2-{sha((kind+'|'+str(value)).encode())[:24]}\"","def key(kind, value): return f\"nexus-{kind}-v1-{sha((kind+'|'+str(value)).encode())[:24]}\""),
("preserve,mpreserve=load('.nexus-d1-secondary-raw-preservation-v2-status/RESULT.json')","preserve,mpreserve=load('.nexus-d1-secondary-raw-preservation-v2-status/RESULT.json')\nnonday,mnonday=load('data/nexus-d1/historical-nonday-dob-fantacalcio-v1/RESULT.json')"),
("assert preserve['status']=='PASS' and preserve['rules']['preservationReplayOnly'] is True","assert preserve['status']=='PASS' and preserve['rules']['preservationReplayOnly'] is True\nassert nonday['status']=='PASS' and nonday['summary']['subjects']==6 and nonday['summary']['dobVerified']==6 and nonday['summary']['requestFailures']==0"),
("hist_override={}\n","hist_override={}\nfor r in nonday['records']:\n    if r.get('dateOfBirth'):\n        hist_override[str(r['subjectId'])]={'dateOfBirth':dob_iso(r['dateOfBirth']),'status':'DOB_VERIFIED','method':'NONDAY_WIKIDATA_REPLACED_BY_D0_BRIDGE_EXACT_FC_CONSENSUS'}\n"),
("'schema':'NEXUS_D1_IDENTITY_MASTER_V2'","'schema':'NEXUS_D1_IDENTITY_MASTER_V3'"),
("'schema':'NEXUS_D1_REGISTRY_V2'","'schema':'NEXUS_D1_REGISTRY_V3'"),
("sources=[mc,mh,msp,mcur2,mhopen,mhconf,mresid,mg445,mo445,mretry,mpreserve]","sources=[mc,mh,msp,mcur2,mhopen,mhconf,mresid,mg445,mo445,mretry,mpreserve,mnonday]"),
("'schema':'NEXUS_D1_FINAL_PACKAGE_MANIFEST_V2'","'schema':'NEXUS_D1_FINAL_PACKAGE_MANIFEST_V3'"),
("'secondaryRawPreservationRelease':'nexus-d1-secondary-raw-preservation-v2'","'secondaryRawPreservationRelease':'nexus-d1-secondary-raw-preservation-v2','historicalNonDayDobRecoveryRelease':'nexus-d1-historical-nonday-dob-fantacalcio-v1'"),
]
for old,new in repls:
    n=src.count(old)
    if n!=1:
        raise RuntimeError(f'FINAL_V3_BASE_PATCH_CARDINALITY:{n}:{old[:80]}')
    src=src.replace(old,new,1)
exec(compile(src,str(p)+'::v3','exec'),{'__name__':'__main__','__file__':str(p)+'::v3'})
