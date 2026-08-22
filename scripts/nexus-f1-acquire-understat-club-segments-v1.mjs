import crypto from 'node:crypto'
import { mkdir, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { buildClubSegmentRecords, extractUnderstatEmbedded, reconcileClubSegmentsToLeague } from './lib/nexus-f1-understat-club-segments-v1.mjs'

const YEARS = Array.from({ length: 12 }, (_, i) => 2014 + i)
const BASE = 'https://understat.com'
const ROOT = process.env.NEXUS_F1_UNDERSTAT_CLUB_OUTPUT ?? '.nexus-f1-understat-club-segments-v1'
const SPACING_MS = Number(process.env.NEXUS_F1_UNDERSTAT_REQUEST_SPACING_MS ?? 500)
const USER_AGENT = 'FantaNexus-F1-RAW/1.1 (noncommercial research acquisition)'
let lastRequestAt = 0
function seasonLabel(year){ return `${year}/${String(year + 1).slice(-2)}` }
function sha256(v){ return crypto.createHash('sha256').update(v).digest('hex') }
function text(v){ return typeof v === 'string' && v.trim().length > 0 }
function sleep(ms){ return new Promise(r=>setTimeout(r,ms)) }
async function rateLimit(){ const elapsed=Date.now()-lastRequestAt; if(elapsed<SPACING_MS) await sleep(SPACING_MS-elapsed); lastRequestAt=Date.now() }
async function fetchText(url){ await rateLimit(); const response=await fetch(url,{headers:{'user-agent':USER_AGENT,accept:'text/html,application/xhtml+xml'}}); const body=await response.text(); if(!response.ok) throw new Error(`HTTP ${response.status} ${url}`); if(!body.includes('JSON.parse')) throw new Error(`Understat payload inatteso ${url}`); return {body,capturedAt:new Date().toISOString(),rawSha256:sha256(body)} }
function normalizeTeams(payload){ const candidate=Array.isArray(payload)?payload:payload?.teams??payload; const rows=Array.isArray(candidate)?candidate:candidate&&typeof candidate==='object'?Object.values(candidate):null; if(!rows||rows.length===0)throw new Error('Understat teamsData vuoto'); return rows.map((t,i)=>{const id=String(t?.id??''),title=String(t?.title??'');if(!text(id)||!text(title))throw new Error(`Understat team ${i}: id/title mancanti`);return{id,title}}) }
function teamUrl(title){ return `${BASE}/team/${encodeURIComponent(title.trim().replace(/\s+/g,'_'))}` }
async function ensureDir(path){ await mkdir(join(ROOT,path),{recursive:true}) }

async function main(){
  await ensureDir('raw'); await ensureDir('normalized')
  const globalAudit={schema:'NEXUS_F1_UNDERSTAT_CLUB_SEGMENTS_ACQUISITION_V1',protocolVersion:'1.1',status:'IN_PROGRESS',acquisitionKind:'NEW_CURRENT_SNAPSHOT_NOT_HISTORICAL_VINTAGE',years:YEARS,seasonAudits:[],governance:{f1Only:true,f2Authorized:false,f3Authorized:false,f4Authorized:false,historicalReplayPromotion:false,availableAtSynthetic:false,canonicalMutation:false}}
  let totalSegmentRows=0,totalMultiClubPlayerSeasons=0
  for(const year of YEARS){
    const season=seasonLabel(year),slug=`${year}-${String(year+1).slice(-2)}`,leagueUrl=`${BASE}/league/Serie_A/${year}`,league=await fetchText(leagueUrl)
    const teams=normalizeTeams(extractUnderstatEmbedded(league.body,'teamsData')),leaguePlayersRaw=extractUnderstatEmbedded(league.body,'playersData'),leaguePlayers=Array.isArray(leaguePlayersRaw)?leaguePlayersRaw:leaguePlayersRaw?.players
    if(!Array.isArray(leaguePlayers)||leaguePlayers.length===0)throw new Error(`${season}: league playersData vuoto`); if(teams.length!==20)throw new Error(`${season}: ${teams.length} squadre, attese 20`)
    await ensureDir(`raw/${slug}`); await writeFile(join(ROOT,`raw/${slug}/league.html`),league.body)
    const segmentRecords=[],teamAudits=[]
    for(const team of teams){const url=`${teamUrl(team.title)}/${year}`,raw=await fetchText(url);await writeFile(join(ROOT,`raw/${slug}/team-${team.id}.html`),raw.body);const playersData=extractUnderstatEmbedded(raw.body,'playersData'),records=buildClubSegmentRecords({season,teamId:team.id,teamTitle:team.title,sourceUrl:url,capturedAt:raw.capturedAt,rawSha256:raw.rawSha256,playersData});segmentRecords.push(...records);teamAudits.push({teamId:team.id,teamTitle:team.title,url,capturedAt:raw.capturedAt,rawSha256:raw.rawSha256,playerRows:records.length})}
    const reconciliation=reconcileClubSegmentsToLeague({clubSegmentRecords:segmentRecords,leaguePlayers,floatTolerance:1e-6}); if(reconciliation.status!=='PASS')throw new Error(`${season}: club/league reconciliation FAIL: ${JSON.stringify({missing:reconciliation.missingSegments.length,extra:reconciliation.extraSegments.length,mismatches:reconciliation.mismatches.slice(0,10)})}`)
    const ndjson=segmentRecords.map(r=>JSON.stringify(r)).join('\n')+'\n',outputSha256=sha256(ndjson);await writeFile(join(ROOT,`normalized/${slug}-club-segments.ndjson`),ndjson)
    const seasonAudit={season,year,leagueUrl,leagueCapturedAt:league.capturedAt,leagueRawSha256:league.rawSha256,leaguePlayerRows:leaguePlayers.length,teams:teams.length,segmentRows:segmentRecords.length,multiClubPlayerSeasons:reconciliation.multiClubPlayers,reconciliation:{status:'PASS',floatTolerance:reconciliation.floatTolerance,missingSegments:0,extraSegments:0,mismatches:0},outputSha256,teamAudits};await writeFile(join(ROOT,`normalized/${slug}-audit.json`),JSON.stringify(seasonAudit,null,2)+'\n');globalAudit.seasonAudits.push(seasonAudit);totalSegmentRows+=segmentRecords.length;totalMultiClubPlayerSeasons+=reconciliation.multiClubPlayers;console.log(`${season}: ${segmentRecords.length} club-segment rows, multi-club ${reconciliation.multiClubPlayers}, reconciliation PASS`)
  }
  globalAudit.status='PASS';globalAudit.completedAt=new Date().toISOString();globalAudit.totalSegmentRows=totalSegmentRows;globalAudit.totalMultiClubPlayerSeasons=totalMultiClubPlayerSeasons;globalAudit.codeCommit=process.env.GITHUB_SHA??null;globalAudit.runtime=process.version;const preHash=JSON.stringify(globalAudit,null,2)+'\n';globalAudit.auditSha256=sha256(preHash);await writeFile(join(ROOT,'audit.json'),JSON.stringify(globalAudit,null,2)+'\n');console.log(JSON.stringify({status:'PASS',totalSegmentRows,totalMultiClubPlayerSeasons,auditSha256:globalAudit.auditSha256},null,2))
}
main().catch(err=>{console.error(err);process.exitCode=1})
