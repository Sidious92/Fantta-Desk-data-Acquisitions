#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path
SRC=Path('.nexus-slgr-fantasy-public-probe-v12-status/RESULT.json')
OUT=Path('.nexus-slgr-fantasy-public-probe-v12-status/SUMMARY.json')
o=json.loads(SRC.read_text(encoding='utf-8'))
uses=[]
for x in o.get('parser_uses',[]):
 uses.append({'parser':x.get('parser'),'offset':x.get('offset'),'request_or_model_classes':x.get('request_or_model_classes') or [],'path_literals':x.get('path_literals') or [],'context':(x.get('context') or '')[:3000]})
classes=[]
for x in o.get('result_class_uses',[]):
 classes.append({'class':x.get('class'),'offset':x.get('offset'),'path_literals':x.get('path_literals') or [],'context':(x.get('context') or '')[:2200]})
res={'schema':'NEXUS_SLGR_FANTASY_PUBLIC_PROBE_V12_SUMMARY','parser_names':o.get('parser_names'),'result_classes':o.get('result_classes'),'occurrences':[{'offset':x.get('offset'),'nearest_function':x.get('nearest_function'),'context':(x.get('context') or '')[:3000]} for x in o.get('occurrences',[])],'parser_uses':uses[:100],'result_class_uses':classes[:100],'governance':o.get('governance')}
OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'parser_names':res['parser_names'],'result_classes':res['result_classes'],'parser_uses':[{'parser':x['parser'],'offset':x['offset'],'classes':x['request_or_model_classes'][:30],'paths':x['path_literals'][:30]} for x in uses[:30]]},ensure_ascii=False,indent=2))
