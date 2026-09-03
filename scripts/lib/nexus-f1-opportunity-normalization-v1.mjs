export const MINUTES_CONVENTION = 'REGULATION_90_CLOCK_V1'

function fail(message) { throw new Error(`Nexus F1 Opportunity normalization: ${message}`) }
function text(value) { return typeof value === 'string' && value.trim().length > 0 }
function normText(value) { return String(value ?? '').trim() }
function eventMinute(event) { const base=Number(event?.time??0),added=Number(event?.additionalTime??0); if(!Number.isFinite(base)||!Number.isFinite(added))return null; return Math.max(0,base+added) }
function regulationMinute(value) { return Math.min(90,Math.max(0,value)) }

export function playerDisplayName(player) { const first=normText(player?.mediaFirstName),last=normText(player?.mediaLastName); return [first,last].filter(Boolean).join(' ')||normText(player?.displayName??player?.shirtName??player?.shortName) }

export function validateLineupPayload(match,lineup) {
  const issues=[],affectedTeamIds=[],matchId=String(match?.matchId??'')
  if(!text(matchId))issues.push('MATCH_ID_MISSING')
  if(!text(String(lineup?.matchId??'')))issues.push('LINEUP_MATCH_ID_MISSING'); else if(matchId&&String(lineup.matchId)!==matchId)issues.push('MATCH_ID_MISMATCH')
  for(const side of ['home','away']){
    const team=match?.[side],starters=lineup?.[side]?.fielded,bench=lineup?.[side]?.benched
    if(!Array.isArray(starters))issues.push(`${side.toUpperCase()}_STARTERS_NOT_ARRAY`)
    if(!Array.isArray(bench))issues.push(`${side.toUpperCase()}_BENCH_NOT_ARRAY`)
    if(!Array.isArray(starters)||!Array.isArray(bench)){if(team?.teamId)affectedTeamIds.push(String(team.teamId));continue}
    if(starters.length!==11)issues.push(`${side.toUpperCase()}_STARTERS_${starters.length}`)
    const ids=[...starters,...bench].map(p=>String(p?.playerId??'')).filter(Boolean),totalPlayers=starters.length+bench.length
    if(ids.length!==totalPlayers)issues.push(`${side.toUpperCase()}_PLAYER_ID_MISSING`)
    if(new Set(ids).size!==ids.length)issues.push(`${side.toUpperCase()}_PLAYER_ID_DUPLICATE`)
    if(starters.length!==11||ids.length!==totalPlayers||new Set(ids).size!==ids.length){if(team?.teamId)affectedTeamIds.push(String(team.teamId))}
  }
  return {ok:issues.length===0,issues,affectedTeamIds:[...new Set(affectedTeamIds)]}
}
function squadItems(match,lineup){const items=[];for(const side of ['home','away']){const team=match?.[side];for(const status of ['fielded','benched'])for(const player of lineup?.[side]?.[status]??[])items.push({side,status,team,player})}return items}

export function deriveParticipationObservation({match,item}) {
  const player=item?.player,sourcePlayerId=String(player?.playerId??''),sourceTeamId=String(item?.team?.teamId??'')
  if(!text(sourcePlayerId))fail('playerId mancante');if(!text(sourceTeamId))fail(`teamId mancante per player ${sourcePlayerId}`)
  const events=Array.isArray(player?.events)?player.events:[],exits=events.filter(e=>['substitution-out','red-card','second-yellow-card'].includes(e?.type)).map(eventMinute).filter(v=>v!==null)
  let appeared=false,started=false,substituteAppearance=false,unusedBench=false,minutes=0
  if(item.status==='fielded'){appeared=true;started=true;minutes=regulationMinute(exits.length?Math.min(...exits):90)}
  else if(item.status==='benched'){const entries=events.filter(e=>e?.type==='substitution-in').map(eventMinute).filter(v=>v!==null);if(entries.length===0){unusedBench=true;minutes=0}else{const enter=Math.min(...entries),laterExits=exits.filter(v=>v>=enter),leave=laterExits.length?Math.min(...laterExits):90;appeared=true;substituteAppearance=true;minutes=Math.max(0,regulationMinute(leave)-regulationMinute(enter))}}
  else fail(`status rosa non supportato: ${item.status}`)
  return {schema:'NEXUS_F1_OPPORTUNITY_PARTICIPATION_RAW_V1',protocolVersion:'1.1',sourceFamily:'OPPORTUNITY_PARTICIPATION',provider:'Lega Serie A Sports Data Platform',sourceMatchId:String(match.matchId),sourcePlayerId,sourceTeamId,season:null,matchDateUtc:String(match.matchDateUtc),club:normText(item.team?.shortName??item.team?.officialName),playerName:playerDisplayName(player),squadStatus:item.status==='fielded'?'STARTER':unusedBench?'UNUSED_BENCH':'SUBSTITUTE_APPEARANCE',observations:{squadSelected:1,appeared:appeared?1:0,started:started?1:0,substituteAppearance:substituteAppearance?1:0,unusedBench:unusedBench?1:0,minutes},missingness:{absentFromSquad:'NOT_MATERIALIZED_AS_NON_APPEARANCE'},minutesConvention:MINUTES_CONVENTION,transformations:'NONE_RAW_EVENT_DERIVATION'}
}

export function normalizeMatchParticipation({season,match,lineup,sourceHash=null,capturedAt=null}) {
  if(!text(season))fail('season obbligatoria');if(!text(String(match?.matchId??''))||!text(String(match?.matchDateUtc??'')))fail('match identity/time incompleti')
  const check=validateLineupPayload(match,lineup)
  if(!check.ok)return {status:'QUARANTINED',season,sourceMatchId:String(match.matchId),matchDateUtc:String(match.matchDateUtc),quarantineReasons:check.issues,affectedTeamIds:check.affectedTeamIds,records:[]}
  const records=squadItems(match,lineup).map(item=>{const record=deriveParticipationObservation({match,item});record.season=season;record.provenance={sourceHash,capturedAt,sourceEventAt:String(match.matchDateUtc),availableAt:null,temporalBasis:'OFFICIAL_MATCH_EVENT_OCCURRENCE'};return record})
  const technical=new Set(records.map(r=>`${r.sourceMatchId}|${r.sourcePlayerId}`));if(technical.size!==records.length)fail(`${season}/${match.matchId}: player duplicato tra i lati o gli status`)
  return {status:'PASS',season,sourceMatchId:String(match.matchId),matchDateUtc:String(match.matchDateUtc),quarantineReasons:[],affectedTeamIds:[],records}
}

export function buildSourceStints(records) {
  const byPlayerSeason=new Map()
  for(const row of records){if(row?.schema!=='NEXUS_F1_OPPORTUNITY_PARTICIPATION_RAW_V1')fail('record schema non supportato');const key=`${row.sourcePlayerId}|${row.season}`,arr=byPlayerSeason.get(key)??[];arr.push(row);byPlayerSeason.set(key,arr)}
  const stints=[]
  for(const rows of byPlayerSeason.values()){
    rows.sort((a,b)=>String(a.matchDateUtc).localeCompare(String(b.matchDateUtc))||String(a.sourceMatchId).localeCompare(String(b.sourceMatchId)))
    let current=null,ordinal=0
    for(const row of rows){if(!current||current.sourceTeamId!==row.sourceTeamId){if(current)stints.push(current);ordinal++;current={schema:'NEXUS_F1_OPPORTUNITY_SOURCE_STINT_V1',protocolVersion:'1.1',provider:row.provider,sourcePlayerId:row.sourcePlayerId,season:row.season,sourceTeamId:row.sourceTeamId,club:row.club,sourceStintOrdinal:ordinal,sourceStintId:`lega:${row.season}:${row.sourcePlayerId}:${ordinal}:${row.sourceTeamId}`,observedFrom:row.matchDateUtc,observedTo:row.matchDateUtc,sourceMatchIds:[],observations:{squadSelections:0,appearances:0,starts:0,substituteAppearances:0,unusedBench:0,minutes:0},canonicalPlayerId:null,canonicalMappingStatus:'PENDING_D1_IDENTITY_AUTHORITY',analyticPromotion:false,transformations:'ADDITIVE_SUM_OF_MATCH_LEVEL_RAW_ONLY',minutesConvention:row.minutesConvention}}
      current.observedTo=row.matchDateUtc;current.sourceMatchIds.push(row.sourceMatchId);current.observations.squadSelections+=row.observations.squadSelected;current.observations.appearances+=row.observations.appeared;current.observations.starts+=row.observations.started;current.observations.substituteAppearances+=row.observations.substituteAppearance;current.observations.unusedBench+=row.observations.unusedBench;current.observations.minutes+=row.observations.minutes}
    if(current)stints.push(current)
  }
  return stints.sort((a,b)=>a.season.localeCompare(b.season)||a.sourcePlayerId.localeCompare(b.sourcePlayerId)||a.sourceStintOrdinal-b.sourceStintOrdinal)
}

export function auditOpportunityNormalization({matchResults,stints}) {
  const admitted=matchResults.filter(x=>x.status==='PASS'),quarantined=matchResults.filter(x=>x.status==='QUARANTINED'),records=admitted.flatMap(x=>x.records),keySet=new Set(records.map(r=>`${r.season}|${r.sourceMatchId}|${r.sourcePlayerId}`))
  if(keySet.size!==records.length)fail('technical key duplicate nella vista partecipazione')
  if(records.some(r=>r.observations.started>r.observations.appeared||r.observations.substituteAppearance>r.observations.appeared))fail('vincoli di partecipazione violati')
  if(records.some(r=>r.observations.unusedBench&&r.observations.appeared))fail('unused bench marcato come appearance')
  const sourceMatchRefs=stints.reduce((n,s)=>n+s.sourceMatchIds.length,0);if(sourceMatchRefs!==records.length)fail('stint aggregation non riconcilia 1:1 i record match-level')
  return {status:'PASS',matchesInput:matchResults.length,matchesAdmitted:admitted.length,matchesQuarantined:quarantined.length,participationRecords:records.length,sourceStints:stints.length,sourceMatchRefs,canonicalMappingsApplied:0,analyticPromotions:0,expectedMinutesBuilt:false}
}
