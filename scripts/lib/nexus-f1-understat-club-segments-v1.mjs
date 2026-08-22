import { F1_SCHEMA_VERSION, validateRawStintRecord } from './nexus-f1-raw-stint-contract-v1.mjs'
import crypto from 'node:crypto'

export const CLUB_SEGMENT_SCHEMA = F1_SCHEMA_VERSION
const EXACT = new Set(['games','time','goals','assists','shots','key_passes','npg'])
const FLOAT = new Set(['xG','npxG','xA','xGChain','xGBuildup'])
const ALL = [...EXACT, ...FLOAT]

function fail(m){ throw new Error(`Nexus F1 Understat club segments: ${m}`) }
function text(v){ return typeof v === 'string' && v.trim().length > 0 }
function num(v,label){ if(v===null||v===undefined||v==='') return null; const n=Number(v); if(!Number.isFinite(n)||n<0) fail(`${label}: numero non negativo richiesto`); return n }
function sha(v){ return typeof v === 'string' && /^[a-f0-9]{64}$/u.test(v) }

export function decodeUnderstatJsString(value){
  return value.replace(/\\x([0-9a-fA-F]{2})/g,(_m,h)=>String.fromCharCode(parseInt(h,16))).replace(/\\u([0-9a-fA-F]{4})/g,(_m,h)=>String.fromCharCode(parseInt(h,16))).replace(/\\\//g,'/').replace(/\\'/g,"'").replace(/\\"/g,'"').replace(/\\n/g,'\n').replace(/\\r/g,'\r').replace(/\\t/g,'\t').replace(/\\\\/g,'\\')
}

export function extractUnderstatEmbedded(html, variable){
  if(!text(html)||!text(variable)) fail('html/variable mancanti')
  const escaped=variable.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')
  const re=new RegExp(`(?:var|let|const)\\s+${escaped}\\s*=\\s*JSON\\.parse\\('([\\s\\S]*?)'\\);`)
  const m=re.exec(html); if(!m) fail(`${variable} non trovato`)
  return JSON.parse(decodeUnderstatJsString(m[1]))
}

export function normalizeUnderstatPlayersData(payload){
  const rows=Array.isArray(payload) ? payload : Array.isArray(payload?.players) ? payload.players : null
  if(!rows) fail('playersData non e un array ne contiene players[]')
  return rows
}

function obs(sourceField,value,unit,semantics){ const n=num(value,sourceField); return {sourceField,value:n,unit,semantics,transformation:'NONE',missingReason:n===null?'NOT_COLLECTED':null} }
function missing(sourceField,unit,semantics){ return {sourceField,value:null,unit,semantics,transformation:'NONE',missingReason:'NOT_COLLECTED'} }

export function buildClubSegmentRecords({season,teamId,teamTitle,sourceUrl,capturedAt,rawSha256,playersData}){
  if(!sha(rawSha256)) fail('rawSha256 non valido')
  const rows=normalizeUnderstatPlayersData(playersData), seen=new Set()
  return rows.map((p,index)=>{
    const sourcePlayerId=String(p.id ?? p.player_id ?? '')
    if(!text(sourcePlayerId)) fail(`${teamTitle}[${index}]: player id mancante`)
    if(seen.has(sourcePlayerId)) fail(`${teamTitle}: player duplicato ${sourcePlayerId}`); seen.add(sourcePlayerId)
    const sourceRecordId=`team:${teamId}:season:${season}:player:${sourcePlayerId}`
    const record={schemaVersion:CLUB_SEGMENT_SCHEMA,protocolVersion:'1.1',recordStatus:'QUARANTINED',quarantineReasons:['MAPPING_UNRESOLVED','STINT_UNRESOLVED','TEMPORAL_UNVERIFIED'],technicalKey:{provider:'UNDERSTAT',competition:'SERIE_A',sourceRecordId,sourceVersion:`UNDERSTAT_TEAM_PAGE@sha256:${rawSha256}`},sourceDimensions:{season,competition:'Serie A',sourceTeamId:String(teamId),club:teamTitle,sourceUrl},analyticKey:{playerId:null,season,league:'Serie A',club:teamTitle,stintId:null,stintOrdinal:null},identity:{sourcePlayerId,mappingStatus:'MAPPING_UNRESOLVED',sourcePlayerName:String(p.player_name ?? p.player ?? '')},provenance:{capturedAt,availableAt:null,sourceHash:rawSha256,temporalStatus:'UNKNOWN',availableAtEvidenceRefs:[]},scope:'PLAYER_SEASON_CLUB_AGGREGATE',providerRules:'UNDERSTAT_TEAM_PAGE_PLAYER_SEASON_CLUB_AGGREGATE_V1',observations:{appearances:obs('games',p.games,'count','Understat team-page games for player and club'),starts:missing('starts','count','Not collected by Understat team-page aggregate'),substituteAppearances:missing('substitute_appearances','count','Not collected by Understat team-page aggregate'),minutes:obs('time',p.time,'minutes','Understat team-page time for player and club'),goals:obs('goals',p.goals,'count','Understat team-page goals'),nonPenaltyGoals:obs('npg',p.npg,'count','Understat team-page non-penalty goals'),assists:obs('assists',p.assists,'count','Understat team-page assists'),xG:obs('xG',p.xG,'expected-goals units','Understat team-page expected goals'),npxG:obs('npxG',p.npxG,'expected-goals units','Understat team-page non-penalty expected goals'),xA:obs('xA',p.xA,'expected-assist units','Understat team-page expected assists'),shots:obs('shots',p.shots,'count','Understat team-page shots'),keyPasses:obs('key_passes',p.key_passes,'count','Understat team-page key passes'),xGChain:obs('xGChain',p.xGChain,'expected-goals units','Understat team-page xGChain'),xGBuildup:obs('xGBuildup',p.xGBuildup,'expected-goals units','Understat team-page xGBuildup'),penaltiesTaken:missing('penalties_taken','count','Not collected by Understat team-page aggregate'),penaltiesScored:missing('penalties_scored','count','Not collected by Understat team-page aggregate')}}
    validateRawStintRecord(record,index); return record
  })
}

function aggregateSegments(records){
  const byPlayer=new Map()
  for(const r of records){
    const id=r.identity.sourcePlayerId
    const cur=byPlayer.get(id) ?? {sourcePlayerId:id,clubs:new Set(),values:Object.fromEntries(ALL.map(k=>[k,0])),missing:Object.fromEntries(ALL.map(k=>[k,0])),recordCount:0}
    cur.clubs.add(r.sourceDimensions.club); cur.recordCount++
    const map={games:'appearances',time:'minutes',goals:'goals',assists:'assists',shots:'shots',key_passes:'keyPasses',npg:'nonPenaltyGoals',xG:'xG',npxG:'npxG',xA:'xA',xGChain:'xGChain',xGBuildup:'xGBuildup'}
    for(const [src,dst] of Object.entries(map)){ const v=r.observations[dst]?.value; if(v!==null&&v!==undefined) cur.values[src]+=v; else cur.missing[src]+=1 }
    byPlayer.set(id,cur)
  }
  return byPlayer
}

export function reconcileClubSegmentsToLeague({clubSegmentRecords,leaguePlayers,floatTolerance=1e-6}){
  if(!Array.isArray(clubSegmentRecords)||!Array.isArray(leaguePlayers)) fail('reconciliation inputs devono essere array')
  const segments=aggregateSegments(clubSegmentRecords), league=new Map()
  for(const p of leaguePlayers){ const id=String(p.id ?? p.player_id ?? ''); if(!text(id)) fail('league player id mancante'); if(league.has(id)) fail(`league player duplicato ${id}`); league.set(id,p) }
  const missingSegments=[],extraSegments=[],mismatches=[]
  for(const [id,p] of league){
    const s=segments.get(id); if(!s){ missingSegments.push(id); continue }
    for(const metric of ALL){ const expected=num(p[metric],`league ${id}.${metric}`); if(expected===null) continue; if(s.missing[metric]>0){mismatches.push({sourcePlayerId:id,metric,reason:'CLUB_SEGMENT_MISSING_METRIC',missingSegmentRows:s.missing[metric],leagueValue:expected});continue} const actual=s.values[metric],diff=Math.abs(actual-expected),ok=EXACT.has(metric)?diff===0:diff<=floatTolerance; if(!ok)mismatches.push({sourcePlayerId:id,metric,leagueValue:expected,clubSum:actual,absoluteDifference:diff}) }
  }
  for(const id of segments.keys()) if(!league.has(id)) extraSegments.push(id)
  const multiClub=[...segments.values()].filter(x=>x.clubs.size>1).map(x=>({sourcePlayerId:x.sourcePlayerId,clubs:[...x.clubs].sort(),segmentRows:x.recordCount})).sort((a,b)=>a.sourcePlayerId.localeCompare(b.sourcePlayerId))
  return {status:missingSegments.length===0&&extraSegments.length===0&&mismatches.length===0?'PASS':'FAIL',leaguePlayers:league.size,segmentPlayers:segments.size,segmentRows:clubSegmentRecords.length,multiClubPlayers:multiClub.length,missingSegments,extraSegments,mismatches,multiClub,floatTolerance}
}

export function deriveObservedStintOrder(matchRows){
  if(!Array.isArray(matchRows)) fail('matchRows deve essere array')
  const sorted=[...matchRows].sort((a,b)=>String(a.matchDate).localeCompare(String(b.matchDate))||String(a.matchId).localeCompare(String(b.matchId))),out=[];let ordinal=0,current=null
  for(const row of sorted){ if(!text(row.sourcePlayerId)||!text(row.sourceTeamId)||!text(row.club)||!text(row.matchDate)||!text(row.matchId)) fail('match row incompleta'); if(!current||current.sourceTeamId!==String(row.sourceTeamId)){ordinal++;current={sourcePlayerId:String(row.sourcePlayerId),sourceTeamId:String(row.sourceTeamId),club:String(row.club),stintOrdinal:ordinal,sourceStintId:`understat:${row.season}:${row.sourcePlayerId}:${ordinal}:${row.sourceTeamId}`,observedFrom:row.matchDate,observedTo:row.matchDate,sourceMatchIds:[String(row.matchId)]};out.push(current)}else{current.observedTo=row.matchDate;current.sourceMatchIds.push(String(row.matchId))} }
  return out
}
