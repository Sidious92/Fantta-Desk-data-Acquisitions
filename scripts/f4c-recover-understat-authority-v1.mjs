#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const OUT = process.env.NEXUS_F4C_RECOVERY_OUT ?? '.nexus-f4c-understat-recovery-v1';
const UA = 'FantaNexus-F4C-Public-Recovery/1.0';
const EXPECTED = {
  2014: '2d7cb9017045897e05d6dc5e41dff3a41e7b3981384af02ca18f310a956f1fbb',
  2015: '6b972b30bf15bf43dc89a9226af35e24b2cb318a1a9f8a2f184bb09e31366545',
  2016: 'e73d5bc115a7310893f605217615f1b154560bdca7b8431e57eb5fb5c5adf942',
  2017: '96077940562478f350b699304359c53e2c4dd24e76528505fce52d6a464d8137',
  2018: 'a93625ceda10fd7e115d1bdbfd39473cd3f1a5485142332402432d70df4a0e4e',
  2019: 'd865ec6d76e24ace677bdbf2404478f1fa54f348ba27d4b17230436ee6a67625',
  2020: '00828384f05817f514ed1bef4835c636347aed3f0e08f1d9ee0606faf72bd83a',
  2021: '51f3fde84c0a87188c96f352b78185005c9bf8ba40bc8d31a72a31c38022aa9c',
  2022: '3f46c1788dcf22deef2673bfd7d9547211ee0fdfec62b0eb3d18e922b2cbdb49',
  2023: '5c424c7a334d9bf43c15fb5f83f0eceec5cfdae8a5891b7b35a61d0b0794731f',
  2024: '56ae389329b7e5ff6b3c7954923bbdfd4b64f0e1ccc5fc091d9453792d084884',
};
const sha256 = (v) => createHash('sha256').update(v).digest('hex');
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const finiteNonNegative = (v) => Number.isFinite(Number(v)) && Number(v) >= 0;
async function fetchText(url, headers = {}) {
  let last;
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    const ctl = new AbortController(); const timer = setTimeout(() => ctl.abort(), 30_000);
    try {
      const r = await fetch(url, { redirect:'follow', signal:ctl.signal, headers:{'User-Agent':UA,...headers} });
      clearTimeout(timer); if (!r.ok) throw new Error(`HTTP_${r.status}_${r.statusText}`); return await r.text();
    } catch(e) { clearTimeout(timer); last=e; if (attempt<4) await sleep(800*attempt); }
  }
  throw last;
}
function teamRows(payload) {
  const teams=payload?.teams; if (!teams || typeof teams!=='object') throw new Error('TEAMS_OBJECT_MISSING');
  return Array.isArray(teams)?teams:Object.values(teams);
}
function validatePayload(payload,year) {
  const teams=teamRows(payload), players=payload?.players;
  if (!Array.isArray(players)||players.length<100) throw new Error(`PLAYERS_INVALID_${year}`);
  if (teams.length!==20) throw new Error(`TEAM_COUNT_${year}_${teams.length}`);
  let historyRows=0;
  for (const team of teams) {
    const title=String(team?.title??team?.name??''), history=team?.history;
    if (!title||!Array.isArray(history)) throw new Error(`TEAM_HISTORY_MISSING_${year}_${title||'UNKNOWN'}`);
    if (history.length!==38) throw new Error(`TEAM_HISTORY_COUNT_${year}_${title}_${history.length}`);
    for (const [i,row] of history.entries()) for (const f of ['xG','npxG']) if (!finiteNonNegative(row?.[f])) throw new Error(`TEAM_${f}_INVALID_${year}_${title}_${i}`);
    historyRows+=history.length;
  }
  for (const [i,p] of players.entries()) {
    if (p?.id===undefined||p?.id===null) throw new Error(`PLAYER_ID_MISSING_${year}_${i}`);
    if (!finiteNonNegative(p?.time)) throw new Error(`PLAYER_TIME_INVALID_${year}_${i}`);
    if (!finiteNonNegative(p?.npxG)) throw new Error(`PLAYER_NPXG_INVALID_${year}_${i}`);
    if (p?.team_title===undefined||p?.team_title===null) throw new Error(`PLAYER_TEAM_TITLE_MISSING_${year}_${i}`);
  }
  return {teamCount:teams.length,teamHistoryRows:historyRows,playerCount:players.length};
}
await mkdir(OUT,{recursive:true});
const result={schema:'NEXUS_F4C_UNDERSTAT_AUTHORITY_RECOVERY_V1',protocolVersion:'1.1',status:'RUNNING',generatedAt:new Date().toISOString(),scientificUse:'SOURCE_RECOVERY_AND_SCHEMA_GATE_ONLY_NO_FEATURE_MATERIALIZATION',seasons:[],exactRawHashMatches:0,exactRawHashMismatches:0,governance:{downstreamFantasyOutcomesUsed:false,canonicalPredictiveEngineModified:false,f5Started:false}};
for (const year of Object.keys(EXPECTED).map(Number).sort((a,b)=>a-b)) {
  const pageUrl=`https://understat.com/league/Serie_A/${year}`, apiUrl=`https://understat.com/getLeagueData/Serie_A/${year}`;
  const page=await fetchText(pageUrl,{Accept:'text/html,application/xhtml+xml'});
  const raw=await fetchText(apiUrl,{Accept:'application/json,text/javascript,*/*;q=0.01','X-Requested-With':'XMLHttpRequest',Referer:pageUrl});
  const actual=sha256(raw), expected=EXPECTED[year], exact=actual===expected;
  let payload,schema; try { payload=JSON.parse(raw); schema=validatePayload(payload,year); } catch(e) { throw new Error(`PAYLOAD_VALIDATION_FAILED_${year}:${e instanceof Error?e.message:String(e)}`); }
  const dir=join(OUT,'raw','understat',String(year)); await mkdir(dir,{recursive:true});
  await writeFile(join(dir,'page.html'),page,'utf8'); await writeFile(join(dir,'league-data.json'),raw,'utf8');
  result.seasons.push({seasonStartYear:year,season:`${year}/${String((year+1)%100).padStart(2,'0')}`,apiUrl,expectedRawSha256:expected,actualRawSha256:actual,exactRawHashMatch:exact,schema});
  if (exact) result.exactRawHashMatches+=1; else result.exactRawHashMismatches+=1; await sleep(500);
}
result.status=result.exactRawHashMismatches===0?'PASS_EXACT_FROZEN_RAW_RECOVERED':'FAIL_RAW_HASH_DRIFT';
await writeFile(join(OUT,'recovery-audit.json'),`${JSON.stringify(result,null,2)}\n`,'utf8');
console.log(JSON.stringify({status:result.status,exactRawHashMatches:result.exactRawHashMatches,exactRawHashMismatches:result.exactRawHashMismatches},null,2));
if (result.status!=='PASS_EXACT_FROZEN_RAW_RECOVERED') process.exitCode=2;
