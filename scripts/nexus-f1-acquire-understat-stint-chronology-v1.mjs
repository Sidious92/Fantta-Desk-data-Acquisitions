import crypto from 'node:crypto'
import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { extractUnderstatEmbedded } from './lib/nexus-f1-understat-club-segments-v1.mjs'
import { applyStintAssignments, buildPlayerObservedChronology } from './lib/nexus-f1-understat-stint-resolution-v1.mjs'

const ROOT=process.env.NEXUS_F1_UNDERSTAT_CLUB_OUTPUT ?? '.nexus-f1-understat-club-segments-v1'
const BASE='https://understat.com'
const SPACING_MS=Number(process.env.NEXUS_F1_UNDERSTAT_REQUEST_SPACING_MS ?? 500)
const USER_AGENT='FantaNexus-F1-RAW/1.1 (noncommercial research acquisition)'
let lastRequestAt=0
function sha256(v){return crypto.createHash('sha256').update(v).digest('hex')}
function sleep(ms){return new Promise(r=>setTimeout(r,ms))}
async function rateLimit(){const e=Date.now()-lastRequestAt;if(e<SPACING_MS)await sleep(SPACING_MS-e);lastRequestAt=Date.now()}
async function fetchText(url){await rateLimit();const response=await fetch(url,{headers:{'user-agent':USER_AGENT,accept:'text/html,application/xhtml+xml'}});const body=await response.text();if(!response.ok)throw new Error(`HTTP ${response.status} ${url}`);if(!body.includes('JSON.parse'))throw new Error(`Understat payload inatteso ${url}`);return {body,capturedAt:new Date().toISOString(),rawSha256:sha256(body)}}
async function readNdjson(path){return (await readFile(path,'utf8')).split(/\r?\n/).filter(Boolean).map(JSON.parse)}
function yearSlug(year){return `${year}-${String(year+1).slice(-2)}`}
function groupByPlayer(records){const m=new Map();for(const r of records){const id=r.identity.sourcePlayerId,a=m.get(id)??[];a.push(r);m.set(id,a)}return m}

async function main(){
  const baseAuditBytes=await readFile(join(ROOT,'audit.json')),baseAudit=JSON.parse(baseAuditBytes.toString('utf8'))
  if(baseAudit.status!=='PASS'||!Array.isArray(baseAudit.seasonAudits)||baseAudit.seasonAudits.length!==12)throw new Error('club-segment base audit non PASS')
  await mkdir(join(ROOT,'raw-player'),{recursive:true});await mkdir(join(ROOT,'raw-match'),{recursive:true});await mkdir(join(ROOT,'resolved'),{recursive:true})
  const seasonData=new Map(),targetPlayers=new Map()
  for(const s of baseAudit.seasonAudits){const records=await readNdjson(join(ROOT,'normalized',`${yearSlug(s.year)}-club-segments.ndjson`));seasonData.set(s.year,records);for(const [playerId,rows] of groupByPlayer(records))if(rows.length>1){const t=targetPlayers.get(playerId)??[];t.push({year:s.year,season:s.season,records:rows});targetPlayers.set(playerId,t)}}
  const playerPages=new Map()
  for(const playerId of [...targetPlayers.keys()].sort((a,b)=>String(a).localeCompare(String(b)))){const url=`${BASE}/player/${playerId}`,raw=await fetchText(url);await writeFile(join(ROOT,'raw-player',`player-${playerId}.html`),raw.body);const matchesData=extractUnderstatEmbedded(raw.body,'matchesData');playerPages.set(playerId,{...raw,url,matchesData})}
  const firstPass=new Map(),ambiguousIds=new Set()
  for(const [playerId,targets] of targetPlayers){const page=playerPages.get(playerId);for(const t of targets){const c=buildPlayerObservedChronology({sourcePlayerId:playerId,seasonStartYear:t.year,clubSegmentRecords:t.records,matchesData:page.matchesData});if(c.status==='FAIL')throw new Error(`${t.season}/${playerId}: chronology source conflict`);firstPass.set(`${t.year}|${playerId}`,c);for(const id of c.requiredMatchRosterIds)ambiguousIds.add(id)}}
  const rosterEvidence=new Map(),matchAudits=[]
  for(const matchId of [...ambiguousIds].sort((a,b)=>String(a).localeCompare(String(b)))){const url=`${BASE}/match/${matchId}`,raw=await fetchText(url);await writeFile(join(ROOT,'raw-match',`match-${matchId}.html`),raw.body);const rostersData=extractUnderstatEmbedded(raw.body,'rostersData');rosterEvidence.set(String(matchId),rostersData);matchAudits.push({matchId:String(matchId),url,capturedAt:raw.capturedAt,rawSha256:raw.rawSha256})}
  const global={schema:'NEXUS_F1_UNDERSTAT_STINT_CHRONOLOGY_AUDIT_V1',protocolVersion:'1.1',status:'PASS',baseClubSegmentAuditSha256:sha256(baseAuditBytes),targetMultiClubSourcePlayers:targetPlayers.size,playerPages:[],matchRosterPages:matchAudits,seasonAudits:[],governance:{structuralAnnotationOnly:true,numericAllocation:false,f1Closed:false,f2Authorized:false,f3Authorized:false,f4Authorized:false,historicalReplayPromotion:false,canonicalMutation:false}}
  for(const [playerId,page] of playerPages)global.playerPages.push({sourcePlayerId:String(playerId),url:page.url,capturedAt:page.capturedAt,rawSha256:page.rawSha256});global.playerPages.sort((a,b)=>a.sourcePlayerId.localeCompare(b.sourcePlayerId))
  for(const s of baseAudit.seasonAudits){const records=seasonData.get(s.year),byPlayer=groupByPlayer(records),chronology={};let chronologyPass=0,chronologyPartial=0;for(const [playerId,rows] of byPlayer){if(rows.length<=1)continue;const page=playerPages.get(playerId),evidence={},first=firstPass.get(`${s.year}|${playerId}`);for(const matchId of first.requiredMatchRosterIds)if(rosterEvidence.has(String(matchId)))evidence[String(matchId)]=rosterEvidence.get(String(matchId));const c=buildPlayerObservedChronology({sourcePlayerId:playerId,seasonStartYear:s.year,clubSegmentRecords:rows,matchesData:page.matchesData,rosterEvidenceByMatch:evidence});c.evidenceRefs=[`UNDERSTAT_PLAYER_PAGE:${playerId}@sha256:${page.rawSha256}`,...c.requiredMatchRosterIds.map(matchId=>{const a=matchAudits.find(x=>x.matchId===String(matchId));return a?`UNDERSTAT_MATCH_ROSTER:${matchId}@sha256:${a.rawSha256}`:`UNDERSTAT_MATCH_ROSTER:${matchId}:MISSING`})];if(c.status==='FAIL')throw new Error(`${s.season}/${playerId}: chronology source conflict after roster evidence`);chronology[playerId]=c;if(c.status==='PASS')chronologyPass++;else chronologyPartial++}const resolved=applyStintAssignments({clubSegmentRecords:records,chronology}),text=resolved.records.map(r=>JSON.stringify(r)).join('\n')+'\n',outputSha256=sha256(text);await writeFile(join(ROOT,'resolved',`${yearSlug(s.year)}-club-stint-view.ndjson`),text);const unresolvedReasons={};for(const a of resolved.audit)if(a.status==='UNRESOLVED')unresolvedReasons[a.reason]=(unresolvedReasons[a.reason]??0)+1;const audit={season:s.season,year:s.year,inputRecords:records.length,chronologyMultiClubPlayers:Object.keys(chronology).length,chronologyPass,chronologyPartial,stintResolvedRecords:resolved.summary.resolved,stintUnresolvedRecords:resolved.summary.unresolved,unresolvedReasons,outputSha256};await writeFile(join(ROOT,'resolved',`${yearSlug(s.year)}-stint-audit.json`),JSON.stringify(audit,null,2)+'\n');global.seasonAudits.push(audit)}
  global.completedAt=new Date().toISOString();global.codeCommit=process.env.GITHUB_SHA??null;global.runtime=process.version;await writeFile(join(ROOT,'stint-chronology-audit.json'),JSON.stringify(global,null,2)+'\n');console.log(JSON.stringify({status:'PASS',targetPlayers:targetPlayers.size,ambiguousMatchRosters:matchAudits.length,seasons:global.seasonAudits.length,unresolved:global.seasonAudits.reduce((n,s)=>n+s.stintUnresolvedRecords,0)},null,2))
}
main().catch(e=>{console.error(e);process.exitCode=1})
