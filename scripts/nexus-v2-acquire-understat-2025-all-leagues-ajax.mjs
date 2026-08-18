import { createHash } from 'node:crypto';
import { mkdir, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

const YEAR = 2025;
const LEAGUES = ['EPL', 'La_liga', 'Bundesliga', 'Ligue_1', 'RFPL'];
const BASE_URL = 'https://understat.com/';
const REQUIRED_PLAYER_KEYS = [
  'id', 'player_name', 'games', 'time', 'goals', 'xG', 'assists', 'xA',
  'shots', 'key_passes', 'yellow_cards', 'red_cards', 'npg', 'npxG',
  'xGChain', 'xGBuildup',
];

function sha256(text) {
  return createHash('sha256').update(text).digest('hex');
}

function num(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function firstCookie(setCookie) {
  return setCookie ? setCookie.split(';', 1)[0] : null;
}

async function acquireLeague(league) {
  const pageUrl = new URL(`league/${league}/${YEAR}`, BASE_URL).href;
  const endpointUrl = new URL(`getLeagueData/${league}/${YEAR}`, BASE_URL).href;
  const userAgent = 'Mozilla/5.0 FantaNexus/2.0 frozen-serving-acquisition';

  const pageResponse = await fetch(pageUrl, {
    headers: { 'user-agent': userAgent },
  });
  const pageHtml = await pageResponse.text();
  if (!pageResponse.ok) {
    throw new Error(`Understat ${league}/${YEAR}: league page HTTP ${pageResponse.status}.`);
  }

  const headers = {
    'user-agent': userAgent,
    accept: 'application/json,text/javascript,*/*;q=0.01',
    referer: pageUrl,
    'x-requested-with': 'XMLHttpRequest',
  };
  const cookie = firstCookie(pageResponse.headers.get('set-cookie'));
  if (cookie) headers.cookie = cookie;

  const response = await fetch(endpointUrl, { headers });
  const raw = await response.text();
  if (!response.ok) {
    throw new Error(`Understat ${league}/${YEAR}: AJAX endpoint HTTP ${response.status}.`);
  }

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch (error) {
    throw new Error(`Understat ${league}/${YEAR}: AJAX endpoint returned invalid JSON: ${error.message}`);
  }

  if (!payload || !Array.isArray(payload.players) || payload.players.length === 0) {
    throw new Error(`Understat ${league}/${YEAR}: AJAX players payload missing or empty.`);
  }

  const missingKeys = REQUIRED_PLAYER_KEYS.filter((key) => !(key in payload.players[0]));
  if (missingKeys.length) {
    throw new Error(`Understat ${league}/${YEAR}: player schema drift: missing ${missingKeys.join(', ')}.`);
  }

  const rows = payload.players.map((r) => ({
    id: String(r.id),
    player_name: String(r.player_name ?? ''),
    games: num(r.games),
    time: num(r.time),
    goals: num(r.goals),
    xG: num(r.xG),
    assists: num(r.assists),
    xA: num(r.xA),
    shots: num(r.shots),
    key_passes: num(r.key_passes),
    yellow_cards: num(r.yellow_cards),
    red_cards: num(r.red_cards),
    npg: num(r.npg),
    npxG: num(r.npxG),
    xGChain: num(r.xGChain),
    xGBuildup: num(r.xGBuildup),
    league,
    year: YEAR,
  }));

  return {
    rows,
    provenance: {
      league,
      pageUrl,
      endpointUrl,
      transport: 'UNDERSTAT_GET_LEAGUE_DATA_AJAX_V1',
      rowCount: rows.length,
      pageRawSha256: sha256(pageHtml),
      rawSha256: sha256(raw),
      responseContentType: response.headers.get('content-type'),
    },
  };
}

async function main() {
  const outputRoot = process.env.NEXUS_V2_UNDERSTAT_2025_OUTPUT_ROOT ?? '.nexus-v2-understat-2025';
  await mkdir(outputRoot, { recursive: true });

  const all = [];
  const provenance = [];
  for (const league of LEAGUES) {
    const result = await acquireLeague(league);
    all.push(...result.rows);
    provenance.push(result.provenance);
  }

  const byLeague = Object.fromEntries(LEAGUES.map((league) => [
    league,
    all.filter((row) => row.league === league).length,
  ]));
  const uniqueIds = new Set(all.map((row) => row.id));
  if (uniqueIds.size === 0) throw new Error('Understat 2025: no player ids acquired.');

  const capturedAt = new Date().toISOString();
  const payload = {
    version: 'nexus-v2-understat-foreign-2025-26-live-final-0.2.0-ajax',
    year: YEAR,
    capturedAt,
    leagues: LEAGUES,
    rowCount: all.length,
    uniquePlayerIds: uniqueIds.size,
    byLeague,
    rows: all,
    provenance,
  };
  const text = `${JSON.stringify(payload)}\n`;
  const payloadSha256 = sha256(text);

  await writeFile(join(outputRoot, 'understat-foreign-2025.json'), text);
  await writeFile(
    join(outputRoot, 'audit.json'),
    `${JSON.stringify({
      version: payload.version,
      year: YEAR,
      capturedAt,
      rowCount: all.length,
      uniquePlayerIds: uniqueIds.size,
      byLeague,
      payloadSha256,
      provenance,
    }, null, 2)}\n`,
  );

  console.log(JSON.stringify({
    status: 'PASS',
    rowCount: all.length,
    uniquePlayerIds: uniqueIds.size,
    byLeague,
    payloadSha256,
  }, null, 2));
}

main();
