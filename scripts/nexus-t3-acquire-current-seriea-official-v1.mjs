import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const BASE = 'https://api-sdp.legaseriea.it/v1/serie-a/football';
const SEASON_ID = 'serie-a::Football_Season::ed7fdc2a3e7b408b942ec177b7b956b5';
const SEASON = '2026-27';
const CUTOFF = '2026-09-05T00:04:00Z';
const SOURCE = 'Lega Serie A Sports Data Platform / Opta';
const OUT = process.env.OUT_DIR || 'out/nexus-t3-current-seriea-official-v1';

fs.mkdirSync(OUT, {recursive:true});
const capturedAt = new Date().toISOString();

function stableJson(x) { return JSON.stringify(x, null, 2) + '\n'; }
function sha256(buf) { return crypto.createHash('sha256').update(buf).digest('hex'); }
async function getJson(url) {
  const r = await fetch(url, {headers:{'accept':'application/json','user-agent':'FantaNexus-T3-readonly/1.0'}});
  if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText} for ${url}`);
  return await r.json();
}

const matchesUrl = `${BASE}/seasons/${encodeURIComponent(SEASON_ID)}/matches?locale=en-GB`;
const matchesPayload = await getJson(matchesUrl);
const allMatches = Array.isArray(matchesPayload?.matches) ? matchesPayload.matches : [];
const cutoffMs = Date.parse(CUTOFF);
const completed = allMatches.filter(m => {
  const t = Date.parse(m.matchDateUtc || '');
  const finished = m.status === 'FINISHED' || m.providerStatus === 'Finished' || m.phase === 'FULL_TIME';
  return finished && Number.isFinite(t) && t <= cutoffMs;
}).sort((a,b) => String(a.matchDateUtc).localeCompare(String(b.matchDateUtc)) || String(a.matchId).localeCompare(String(b.matchId)));

const rawMatches = {source:SOURCE,capturedAt,url:matchesUrl,cutoff:CUTOFF,seasonId:SEASON_ID,season:SEASON,payload:matchesPayload};
const matchesBytes = Buffer.from(stableJson(rawMatches));
fs.writeFileSync(path.join(OUT,'matches.json'), matchesBytes);

const rows = [];
const failures = [];
for (const m of completed) {
  const url = `${BASE}/seasons/${encodeURIComponent(SEASON_ID)}/matches/${encodeURIComponent(m.matchId)}/lineups?locale=en-GB`;
  try {
    const lineup = await getJson(url);
    rows.push({seasonId:SEASON_ID,seasonName:'2026/2027',capturedAt,source:SOURCE,sourceUrl:url,match:m,lineup});
  } catch (e) {
    failures.push({matchId:m.matchId,kickoff:m.matchDateUtc,error:String(e?.message || e)});
  }
}
const lineupsText = rows.map(r=>JSON.stringify(r)).join('\n') + (rows.length?'\n':'');
const lineupsBytes = Buffer.from(lineupsText);
fs.writeFileSync(path.join(OUT,'lineups.ndjson'), lineupsBytes);

const manifest = {
  schemaVersion:'nexus.t3.current-seriea-official-acquisition.v1',
  status: failures.length === 0 ? 'ACQUIRED_ALL_COMPLETED_MATCHES_BY_CUTOFF' : 'PARTIAL_FAIL_CLOSED',
  source:SOURCE,
  baseUrl:BASE,
  seasonId:SEASON_ID,
  season:SEASON,
  cutoff:CUTOFF,
  capturedAt,
  matchesCatalogueCount:allMatches.length,
  completedMatchesByCutoff:completed.length,
  lineupPayloadsAcquired:rows.length,
  lineupFailures:failures,
  files:{
    'matches.json':{bytes:matchesBytes.length,sha256:sha256(matchesBytes)},
    'lineups.ndjson':{bytes:lineupsBytes.length,sha256:sha256(lineupsBytes)}
  },
  acquisitionOnly:true,
  absenceOfRowNeverMeansDnp:true,
  noFutureData:true
};
const manifestBytes = Buffer.from(stableJson(manifest));
fs.writeFileSync(path.join(OUT,'manifest.json'), manifestBytes);
console.log(stableJson(manifest));
if (failures.length) process.exitCode = 2;
