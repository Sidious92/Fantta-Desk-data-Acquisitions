#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'

const CONFIG_PATH='config/nexus-f1-lega-snapshot-v1.json'
const C=JSON.parse(fs.readFileSync(CONFIG_PATH,'utf8'))
const ROOT='.nexus-f1-lega-snapshot-v1', RAW=path.join(ROOT,'raw')
const hash=v=>crypto.createHash('sha256').update(v).digest('hex')
const fileHash=p=>hash(fs.readFileSync(p))
const sleep=ms=>new Promise(r=>setTimeout(r,ms))
const enc=encodeURIComponent
const safe=v=>String(v).replace(/[^A-Za-z0-9._-]+/gu,'_')
const mkdir=p=>fs.mkdirSync(p,{recursive:true})
const write=(p,v)=>{mkdir(path.dirname(p));fs.writeFileSync(p,v)}
const json=(p,v)=>write(p,JSON.stringify(v,null,2)+'\n')
const fail=m=>{throw new Error(`Nexus F1 Lega snapshot v2: ${m}`)}

if(C.schema!=='NEXUS_F1_LEGA_SNAPSHOT_CONFIG_V1'||C.protocolVersion!=='1.1')fail('config mismatch')
if(C.oldArtifact?.freshSnapshotIsRecovery!==false)fail('fresh snapshot cannot be old-artifact recovery')
if(C.governance?.rawOnly!==true||C.governance?.normalizationAllowed!==false||C.governance?.stintDerivationAllowed!==false)fail('RAW governance mismatch')
fs.rmSync(ROOT,{recursive:true,force:true});mkdir(RAW)

let last=0,calls=0
const log=[]
async function get(url,id){
  const wait=Math.max(0,Number(C.requestDelayMs)-(Date.now()-last));if(wait)await sleep(wait)
  let error
  for(let attempt=1;attempt<=Number(C.maxRetries)+1;attempt++){
    const requestedAt=new Date().toISOString(), ctrl=new AbortController(), timer=setTimeout(()=>ctrl.abort(),Number(C.requestTimeoutMs))
    try{
      last=Date.now();const r=await fetch(url,{headers:{accept:'application/json','user-agent':C.userAgent},signal:ctrl.signal});const text=await r.text();clearTimeout(timer);calls++
      const receivedAt=new Date().toISOString(), headers={date:r.headers.get('date'),etag:r.headers.get('etag'),lastModified:r.headers.get('last-modified'),contentType:r.headers.get('content-type')}
      const meta={id,url,attempt,requestedAt,receivedAt,status:r.status,ok:r.ok,headers,bytes:Buffer.byteLength(text),sha256:hash(text)};log.push(meta)
      if(!r.ok){error=new Error(`HTTP ${r.status} ${id}`)}else{
        let body;try{body=JSON.parse(text)}catch{throw new Error(`non-JSON ${id}`)}
        return {...meta,text,body}
      }
    }catch(e){clearTimeout(timer);error=e}
    if(attempt<=Number(C.maxRetries))await sleep(750*attempt)
  }
  throw error
}

function matchdayNumber(match){
  const providerId=match?.matchSet?.providerId
  const m=typeof providerId==='string'?/^opta:MatchDay:(\d+)$/u.exec(providerId):null
  return m?Number(m[1]):null
}
function regularSeasonSelection(matches){
  if(!Array.isArray(matches))fail('matches must be array')
  const selected=[],excluded=[]
  for(const m of matches){
    const matchId=m?.matchId??m?.id??null
    const md=matchdayNumber(m)
    if(Number.isInteger(md)&&md>=1&&md<=38){
      if(!matchId)fail('regular-season match without matchId')
      if(!m?.matchDateUtc)fail(`regular-season match ${matchId} without matchDateUtc`)
      selected.push(m)
    }else{
      excluded.push({
        matchId:matchId===null?null:String(matchId),
        matchDateUtc:m?.matchDateUtc??null,
        matchStatus:m?.status??null,
        matchSetProviderId:m?.matchSet?.providerId??null,
        matchSetName:m?.matchSet?.name??null,
        exclusionReason:'MATCHSET_NOT_REGULAR_MATCHDAY_1_38'
      })
    }
  }
  selected.sort((a,b)=>String(a.matchDateUtc).localeCompare(String(b.matchDateUtc))||String(a.matchId??a.id).localeCompare(String(b.matchId??b.id)))
  const ids=selected.map(m=>String(m.matchId??m.id))
  if(new Set(ids).size!==ids.length)fail('duplicate matchId in selected regular season')
  return {selected,excluded}
}

const base=C.baseUrl.replace(/\/$/u,''), locale=enc(C.locale), startedAt=new Date().toISOString()
const catalog=await get(`${base}/competitions/${enc(C.competitionId)}/seasons?locale=${locale}`,'season-catalog')
if(!Array.isArray(catalog.body?.seasons)||!catalog.body.seasons.length)fail('catalog seasons[] missing')
const catalogPath=path.join(RAW,'season-catalog.json');write(catalogPath,catalog.text)
const files=[{path:catalogPath,id:'season-catalog',sha256:catalog.sha256,bytes:catalog.bytes,capturedAt:catalog.receivedAt,availableAt:null,responseHeaders:catalog.headers}]
const selected=C.targetSeasons.map(name=>{const row=catalog.body.seasons.find(s=>(s.seasonName??s.name)===name);if(!row?.seasonId)fail(`season missing ${name}`);return{name,id:row.seasonId}})
if(new Set(selected.map(s=>s.id)).size!==selected.length)fail('duplicate season ids')
const seasons=[]

for(const s of selected){
  const dir=path.join(RAW,safe(s.name))
  const mr=await get(`${base}/seasons/${enc(s.id)}/matches?locale=${locale}`,`matches:${s.name}`)
  if(!Array.isArray(mr.body?.matches))fail(`matches[] missing ${s.name}`)
  const sourceMatches=mr.body.matches
  const selection=regularSeasonSelection(sourceMatches)
  const matches=selection.selected, ids=matches.map(m=>String(m.matchId??m.id))
  if(matches.length!==Number(C.expectedRegularSeasonMatchesPerSeason)){
    fail(`regular-season match count ${s.name}: selected ${matches.length} from ${sourceMatches.length} source rows; expected ${C.expectedRegularSeasonMatchesPerSeason}`)
  }
  const mp=path.join(dir,'matches.json');write(mp,mr.text);files.push({path:mp,id:`matches:${s.name}`,sha256:mr.sha256,bytes:mr.bytes,capturedAt:mr.receivedAt,availableAt:null,responseHeaders:mr.headers})
  const lineups=[]
  for(let i=0;i<matches.length;i++){
    const m=matches[i], id=ids[i]
    const lr=await get(`${base}/seasons/${enc(s.id)}/matches/${enc(id)}/lineups?locale=${locale}`,`lineup:${s.name}:${id}`)
    if(!lr.body||typeof lr.body!=='object'||Array.isArray(lr.body)||!Object.keys(lr.body).length)fail(`empty lineup ${s.name}:${id}`)
    const p=path.join(dir,'lineups',`${String(i+1).padStart(3,'0')}-${safe(id)}.json`);write(p,lr.text)
    const rec={matchId:id,matchDateUtc:m.matchDateUtc??null,matchStatus:m.status??null,matchday:matchdayNumber(m),matchSetProviderId:m.matchSet?.providerId??null,homeTeamId:m.home?.teamId??null,awayTeamId:m.away?.teamId??null,file:p,sha256:lr.sha256,bytes:lr.bytes,capturedAt:lr.receivedAt,availableAt:null,responseHeaders:lr.headers};lineups.push(rec)
    files.push({path:p,id:`lineup:${s.name}:${id}`,sha256:lr.sha256,bytes:lr.bytes,capturedAt:lr.receivedAt,availableAt:null,responseHeaders:lr.headers})
  }
  seasons.push({
    seasonName:s.name,
    seasonId:s.id,
    sourceMatchRows:sourceMatches.length,
    regularSeasonSelectionRule:'matchSet.providerId matches ^opta:MatchDay:(1..38)$',
    matchCount:matches.length,
    uniqueMatchIds:new Set(ids).size,
    excludedSourceMatches:selection.excluded,
    lineupPayloadCount:lineups.length,
    matchesFile:mp,
    matchesSha256:mr.sha256,
    lineups
  })
  console.log(`${s.name}: ${sourceMatches.length} source rows -> ${matches.length} regular matches / ${lineups.length} lineups; excluded ${selection.excluded.length}`)
}

const responseLog=path.join(ROOT,'response-log.json');json(responseLog,log)
const index=files.map(f=>`${f.path}|${f.sha256}|${f.bytes}`).sort().join('\n'), snapshotContentSha256=hash(index)
const manifest={schema:'NEXUS_F1_LEGA_RAW_SNAPSHOT_MANIFEST_V1',protocolVersion:'1.1',status:'FRESH_RAW_SNAPSHOT_CAPTURED_NOT_F1_PROMOTED',purpose:C.purpose,source:{provider:'Lega Serie A',surface:'Sports Data Platform',baseUrl:C.baseUrl,competitionId:C.competitionId},freshAcquisition:true,oldArtifactReference:C.oldArtifact,startedAt,completedAt:new Date().toISOString(),codeCommit:process.env.GITHUB_SHA??'LOCAL_UNKNOWN',githubRunId:process.env.GITHUB_RUN_ID?Number(process.env.GITHUB_RUN_ID):null,githubRunAttempt:process.env.GITHUB_RUN_ATTEMPT?Number(process.env.GITHUB_RUN_ATTEMPT):null,runtime:process.version,randomSeed:'NOT_APPLICABLE_DETERMINISTIC_ACQUISITION',configurationPath:CONFIG_PATH,configurationSha256:fileHash(CONFIG_PATH),temporalPolicy:C.temporalPolicy,availableAtPolicy:'UNASSIGNED_IN_RAW_SNAPSHOT; provider event timestamps and HTTP response metadata preserved separately',regularSeasonSelection:{rule:'matchSet.providerId opta:MatchDay:1..38',authority:'FantaDesk scripts/lib/nexus-f1-opportunity-acquisition-v1.mjs',excludedRowsPreservedInSeasonManifest:true},catalog:{file:catalogPath,sha256:catalog.sha256,bytes:catalog.bytes,seasonCatalogRows:catalog.body.seasons.length},seasons,totals:{seasons:seasons.length,sourceMatchRows:seasons.reduce((a,s)=>a+s.sourceMatchRows,0),excludedSourceMatches:seasons.reduce((a,s)=>a+s.excludedSourceMatches.length,0),matches:seasons.reduce((a,s)=>a+s.matchCount,0),lineupPayloads:seasons.reduce((a,s)=>a+s.lineupPayloadCount,0),successfulHttpResponses:log.filter(x=>x.ok).length,failedAttempts:log.filter(x=>!x.ok).length,callsIncludingFailedAttempts:calls},snapshotContentSha256,contentIndexDefinition:'SHA256 over sorted path|sha256|bytes for raw source files only',responseLog:{file:responseLog,sha256:fileHash(responseLog)},semanticLineupValidationPerformed:false,normalizationPerformed:false,stintDerivationPerformed:false,historicalReplayPromotion:false,f1Closed:false,f2PlusAuthorized:false,canonicalMutation:false}
const manifestPath=path.join(ROOT,'manifest.json');json(manifestPath,manifest);const manifestSha256=fileHash(manifestPath)
const audit={schema:'NEXUS_F1_LEGA_RAW_SNAPSHOT_AUDIT_V1',protocolVersion:'1.1',status:'PASS_RAW_ACQUISITION_ONLY',manifestSha256,snapshotContentSha256,expectedSeasons:C.targetSeasons.length,observedSeasons:seasons.length,sourceMatchRows:manifest.totals.sourceMatchRows,excludedSourceMatches:manifest.totals.excludedSourceMatches,expectedMatches:C.targetSeasons.length*Number(C.expectedRegularSeasonMatchesPerSeason),observedMatches:manifest.totals.matches,expectedLineupPayloads:C.targetSeasons.length*Number(C.expectedRegularSeasonMatchesPerSeason),observedLineupPayloads:manifest.totals.lineupPayloads,regularSeasonSelectionRule:'matchSet.providerId opta:MatchDay:1..38',oldArtifactRecovered:false,availableAtAssigned:false,normalizationPerformed:false,stintDerivationPerformed:false,f1Closed:false,nextRequiredStep:'SEMANTIC_LINEUP_AUDIT_AND_F1_RAW_STINT_DERIVATION_WITH_RECONCILIATION'}
json(path.join(ROOT,'audit.json'),audit)
console.log(JSON.stringify({...audit,calls:manifest.totals.callsIncludingFailedAttempts},null,2))
