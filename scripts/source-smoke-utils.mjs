export function summarizeOpenFootball(data, asOf = new Date()) {
  if (!Array.isArray(data?.matches)) throw new Error('matches array missing');
  const matches=data.matches;
  const completed=matches.filter(x=>Array.isArray(x.score?.ft)&&x.score.ft.length===2).length;
  const overdue=matches.filter(x=>/^\d{4}-\d{2}-\d{2}$/.test(x.date??'')&&Date.parse(x.date+'T23:59:59Z')<+asOf-48*3600*1000&&!(Array.isArray(x.score?.ft)&&x.score.ft.length===2)).length;
  return {season:data.name??null,matches:matches.length,completed,overdue,teams:[...new Set(matches.flatMap(x=>[x.team1,x.team2]))].filter(Boolean).length};
}
export function summarizeStatsBomb(data) {
  if(!Array.isArray(data)) throw new Error('competitions array missing');
  return {competitionSeasons:data.filter(x=>x.country_name==='Italy'&&x.competition_name==='Serie A').map(x=>x.season_name).sort()};
}
export function summarizeWikidata(data,id='Q615') {
  const e=data?.entities?.[id]; if(!e?.id)throw new Error('entity not resolved');
  return {entityId:e.id,name:e.labels?.en?.value??null,dateOfBirthPresent:Array.isArray(e.claims?.P569)&&e.claims.P569.length>0};
}
export function redactError(s) {
  return String(s??'').replace(/(x-apisports-key|x-auth-token|api_key|token|key)\s*[:=]\s*\S+/gi,'$1=<REDACTED>').slice(0,180);
}
