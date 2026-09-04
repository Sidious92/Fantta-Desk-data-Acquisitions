import { createHash } from 'node:crypto';
import { mkdir, writeFile, appendFile, readFile, readdir, stat } from 'node:fs/promises';
import { dirname, join, relative } from 'node:path';

const ROOT = process.env.NEXUS_T0A_OUTPUT ?? '.nexus-t0a-official-reacquisition-v1';
const BASE = 'https://api-sdp.legaseriea.it/v1/serie-a/football';
const COMPETITION_ID = 'serie-a::Football_Competition::ec93b94f74294dc98ab5bcfd67fc0d88';
const COMPETITION = 'Serie A';
const USER_AGENT = 'FantaNexus-T0A-Exact-Scope-Official-Reacquisition/1.0';
const SPACING_MS = Number(process.env.NEXUS_REQUEST_SPACING_MS ?? 500);
const TIMEOUT_MS = Number(process.env.NEXUS_REQUEST_TIMEOUT_MS ?? 30000);
const MINUTES_CONVENTION = 'REGULATION_90_CLOCK_V1';
const HISTORICAL_PIN = '9b6b516c349cf2ba02fef70886d3749d2b7b6f0e';
const NORMALIZER_PIN = 'nexus-historical-normalizer-0.2.0';
const SEASONS = [
  { seasonName: '2021/2022', slug: '2021-22', expectedUsable: 380 },
  { seasonName: '2022/2023', slug: '2022-23', expectedUsable: 380 },
  { seasonName: '2023/2024', slug: '2023-24', expectedUsable: 380 },
  { seasonName: '2024/2025', slug: '2024-25', expectedUsable: 379 },
  { seasonName: '2025/2026', slug: '2025-26', expectedUsable: 380 },
];
const HISTORICAL_KNOWN_INCOMPLETE = 'serie-a::Football_Match::6b8d65604bb549edb97a60ea1344292e';
const capturedAt = new Date().toISOString();
let lastRequestAt = 0;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function ensureParent(path) { await mkdir(dirname(path), { recursive: true }); }
async function saveJson(path, value) { const p = join(ROOT, path); await ensureParent(p); await writeFile(p, `${JSON.stringify(value, null, 2)}\n`); }
function withLocale(path) { const s = path.includes('?') ? '&' : '?'; return `${BASE}${path}${s}locale=en-GB`; }
function sha256(buffer) { return createHash('sha256').update(buffer).digest('hex'); }
async function rateLimit() { const elapsed = Date.now() - lastRequestAt; if (elapsed < SPACING_MS) await sleep(SPACING_MS - elapsed); lastRequestAt = Date.now(); }
async function fetchJson(url) {
  let lastError;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await rateLimit();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const r = await fetch(url, { method: 'GET', redirect: 'follow', headers: { Accept: 'application/json', 'User-Agent': USER_AGENT }, signal: controller.signal });
      clearTimeout(timer);
      if (!r.ok) throw new Error(`HTTP ${r.status} ${r.statusText} for ${url}`);
      return await r.json();
    } catch (e) { clearTimeout(timer); lastError = e; if (attempt < 3) await sleep(700 * attempt); }
  }
  throw lastError;
}
function regularMatchday(match) {
  const idx = Number(match?.matchSet?.index);
  if (Number.isInteger(idx) && idx >= 1 && idx <= 38) return idx;
  const m = String(match?.matchSet?.providerId ?? '').match(/^opta:MatchDay:(\d+)$/);
  if (m) { const n = Number(m[1]); if (n >= 1 && n <= 38) return n; }
  return null;
}
function playerName(p) {
  const f = String(p?.mediaFirstName ?? '').trim(), l = String(p?.mediaLastName ?? '').trim();
  return [f,l].filter(Boolean).join(' ') || String(p?.displayName ?? p?.shirtName ?? p?.shortName ?? '').trim() || null;
}
function eventMinute(e) {
  const a = Number(e?.time ?? 0), b = Number(e?.additionalTime ?? 0);
  return Number.isFinite(a) && Number.isFinite(b) ? Math.max(0, a + b) : null;
}
function rMinute(v) { return Math.min(90, Math.max(0, v)); }
function sideRows(record, side) {
  const team = record.match?.[side] ?? null;
  const opponent = record.match?.[side === 'home' ? 'away' : 'home'] ?? null;
  const block = record.lineup?.[side] ?? {};
  const out = [];
  for (const p of block.fielded ?? []) out.push({ p, sourceStatus: 'fielded', team, opponent });
  for (const p of block.benched ?? []) out.push({ p, sourceStatus: 'benched', team, opponent });
  return out;
}
function validateLineup(record) {
  const issues = [];
  if (!record.match?.matchId || record.lineup?.matchId !== record.match.matchId) issues.push('MATCH_ID_MISMATCH');
  for (const side of ['home','away']) {
    const f = record.lineup?.[side]?.fielded ?? [];
    const b = record.lineup?.[side]?.benched ?? [];
    const ids = [...f,...b].map((p) => p?.playerId);
    if (f.length !== 11) issues.push(`${side.toUpperCase()}_STARTERS_${f.length}`);
    if (ids.some((x) => !x)) issues.push(`${side.toUpperCase()}_SQUAD_ID_MISSING`);
    if (new Set(ids).size !== ids.length) issues.push(`${side.toUpperCase()}_SQUAD_ID_DUPLICATE`);
  }
  return issues;
}
function normalizePlayer(record, item, seasonSlug) {
  const events = Array.isArray(item.p?.events) ? item.p.events : [];
  const starter = item.sourceStatus === 'fielded';
  const namedOnBench = item.sourceStatus === 'benched';
  const inEvents = events.filter((e) => e?.type === 'substitution-in');
  const outEvents = events.filter((e) => ['substitution-out','red-card','second-yellow-card'].includes(e?.type));
  const inMinutes = inEvents.map(eventMinute);
  const outMinutes = outEvents.map(eventMinute);
  if (inMinutes.some((v) => v === null) || outMinutes.some((v) => v === null)) return { error: 'UNOBSERVABLE_EVENT_MINUTE' };
  const substituteEntered = namedOnBench ? inEvents.length > 0 : false;
  let minutesPlayed;
  if (starter) {
    const exits = outMinutes;
    minutesPlayed = rMinute(exits.length ? Math.min(...exits) : 90);
  } else if (!substituteEntered) {
    minutesPlayed = 0;
  } else {
    const enter = Math.min(...inMinutes);
    const exits = outMinutes.filter((v) => v >= enter);
    minutesPlayed = Math.max(0, rMinute(exits.length ? Math.min(...exits) : 90) - rMinute(enter));
  }
  const appeared = starter || substituteEntered;
  const unusedBench = namedOnBench ? !substituteEntered : false;
  return {
    row: {
      season: seasonSlug,
      competition: COMPETITION,
      matchId: record.match.matchId,
      kickoff: record.match.matchDateUtc ?? null,
      clubId: item.team?.teamId ?? null,
      opponentId: item.opponent?.teamId ?? null,
      legaPlayerId: item.p?.playerId ?? null,
      legaProviderId: item.p?.providerId ?? null,
      playerName: playerName(item.p),
      starter,
      namedOnBench,
      substituteEntered,
      unusedBench,
      appeared,
      minutesPlayed,
      minutesConvention: MINUTES_CONVENTION,
      source: 'Lega Serie A Sports Data Platform / Opta',
      provenance: {
        base: BASE,
        lineupEndpoint: `/seasons/${record.seasonId}/matches/${record.match.matchId}/lineups`,
        historicalCollectorCommit: HISTORICAL_PIN,
        historicalNormalizerVersion: NORMALIZER_PIN,
        sourceStatus: item.sourceStatus
      },
      capturedAt
    }
  };
}
async function walk(dir) {
  const entries = [];
  for (const name of await readdir(dir)) {
    const path = join(dir, name); const s = await stat(path);
    if (s.isDirectory()) entries.push(...await walk(path)); else entries.push(path);
  }
  return entries;
}

async function main() {
  await mkdir(ROOT, { recursive: true });
  await saveJson('preregistration-runtime.json', {
    schema: 'T0A_RUNTIME_PREREG_ECHO_V1', capturedAt, sourceMode: 'GET_ONLY',
    base: BASE, competitionId: COMPETITION_ID, seasons: SEASONS,
    forbidden: ['T1','models','new providers','new competitions','serving','Decision Layer']
  });

  const catalogueUrl = withLocale(`/competitions/${COMPETITION_ID}/seasons`);
  const catalogue = await fetchJson(catalogueUrl);
  await saveJson('raw/seriea/seasons-catalogue.json', { source: 'Lega Serie A Sports Data Platform / Opta', capturedAt, url: catalogueUrl, payload: catalogue });
  const catSeasons = Array.isArray(catalogue.seasons) ? catalogue.seasons : [];
  const selected = SEASONS.map((wanted) => {
    const found = catSeasons.find((s) => s.seasonName === wanted.seasonName);
    if (!found) throw new Error(`SOURCE_NO_LONGER_REPRODUCIBLE: season missing ${wanted.seasonName}`);
    return { ...wanted, seasonId: found.seasonId, catalogue: found };
  });
  await saveJson('raw/seriea/selected-seasons.json', selected);

  const coverage = [];
  const normalizedPath = join(ROOT, 'normalized/player-match.ndjson');
  await ensureParent(normalizedPath); await writeFile(normalizedPath, '');
  const uniqueness = new Set();

  for (const season of selected) {
    const matchesUrl = withLocale(`/seasons/${season.seasonId}/matches`);
    const matchesPayload = await fetchJson(matchesUrl);
    await saveJson(`raw/seriea/${season.slug}/matches.json`, { source: 'Lega Serie A Sports Data Platform / Opta', capturedAt, url: matchesUrl, payload: matchesPayload });
    const allMatches = Array.isArray(matchesPayload.matches) ? matchesPayload.matches : [];
    const regular = allMatches.filter((m) => regularMatchday(m) !== null);
    if (regular.length !== 380) throw new Error(`SOURCE_NO_LONGER_REPRODUCIBLE: ${season.slug} regular matches ${regular.length} != 380`);
    const ordered = [...regular].sort((a,b) => String(a.matchDateUtc ?? '').localeCompare(String(b.matchDateUtc ?? '')) || String(a.matchId ?? '').localeCompare(String(b.matchId ?? '')));
    const rawLineupsPath = join(ROOT, `raw/seriea/${season.slug}/lineups.ndjson`); await ensureParent(rawLineupsPath); await writeFile(rawLineupsPath, '');
    const seasonAudit = [];
    let usable = 0, rows = 0, identityMissing = 0, invalidEventMinuteMatches = 0;
    for (let i = 0; i < ordered.length; i += 1) {
      const match = ordered[i];
      const url = withLocale(`/seasons/${season.seasonId}/matches/${match.matchId}/lineups`);
      let lineup;
      try { lineup = await fetchJson(url); }
      catch (e) { seasonAudit.push({ matchId: match.matchId, matchday: regularMatchday(match), status: 'FETCH_FAILED', error: String(e?.message ?? e) }); continue; }
      const record = { seasonId: season.seasonId, seasonName: season.seasonName, capturedAt, sourceUrl: url, match, lineup };
      await appendFile(rawLineupsPath, `${JSON.stringify(record)}\n`);
      const issues = validateLineup(record);
      if (issues.length) { seasonAudit.push({ matchId: match.matchId, matchday: regularMatchday(match), status: 'INCOMPLETE_FAIL_CLOSED', issues, home: match.home?.shortName ?? null, away: match.away?.shortName ?? null }); continue; }
      const candidateRows = [];
      let rowError = null;
      for (const side of ['home','away']) for (const item of sideRows(record, side)) {
        const n = normalizePlayer(record, item, season.slug);
        if (n.error) { rowError = n.error; break; }
        if (!n.row.legaPlayerId || !n.row.playerName || !n.row.clubId || !n.row.opponentId) identityMissing += 1;
        const key = `${n.row.season}|${n.row.matchId}|${n.row.clubId}|${n.row.legaPlayerId}`;
        if (uniqueness.has(key)) { rowError = `DUPLICATE_PLAYER_CLUB_MATCH:${key}`; break; }
        candidateRows.push({ key, row: n.row });
      }
      if (rowError) { invalidEventMinuteMatches += 1; seasonAudit.push({ matchId: match.matchId, matchday: regularMatchday(match), status: 'INCOMPLETE_FAIL_CLOSED', issues: [rowError] }); continue; }
      const startersByClub = new Map();
      for (const x of candidateRows) if (x.row.starter) startersByClub.set(x.row.clubId, (startersByClub.get(x.row.clubId) ?? 0) + 1);
      if ([...startersByClub.values()].length !== 2 || [...startersByClub.values()].some((n) => n !== 11)) {
        seasonAudit.push({ matchId: match.matchId, matchday: regularMatchday(match), status: 'INCOMPLETE_FAIL_CLOSED', issues: ['NORMALIZED_STARTER_COUNT_INVALID'] }); continue;
      }
      for (const x of candidateRows) { uniqueness.add(x.key); await appendFile(normalizedPath, `${JSON.stringify(x.row)}\n`); rows += 1; }
      usable += 1;
      seasonAudit.push({ matchId: match.matchId, matchday: regularMatchday(match), status: 'USABLE', normalizedRows: candidateRows.length });
      if ((i + 1) % 50 === 0 || i + 1 === ordered.length) console.log(`${season.slug}: ${i + 1}/${ordered.length}`);
    }
    await saveJson(`normalized/audit-${season.slug}.json`, seasonAudit);
    const historicalMatchIdsNotUsable = seasonAudit.filter((x) => x.status !== 'USABLE').map((x) => x.matchId);
    coverage.push({
      season: season.slug, seasonId: season.seasonId, regularMatches: regular.length, usableMatches: usable,
      expectedHistoricalUsableMatches: season.expectedUsable, drift: usable - season.expectedUsable,
      normalizedRows: rows, identityMissing, invalidEventMinuteMatches,
      unusableMatchIds: historicalMatchIdsNotUsable,
      historicalKnownIncompleteObserved: season.slug === '2024-25' ? historicalMatchIdsNotUsable.includes(HISTORICAL_KNOWN_INCOMPLETE) : null
    });
  }

  await saveJson('normalized/coverage-manifest.json', { schema: 'NEXUS_T0A_COVERAGE_MANIFEST_V1', capturedAt, coverage });
  const filesBeforeManifest = await walk(ROOT);
  const fileManifest = [];
  for (const path of filesBeforeManifest.sort()) {
    const buf = await readFile(path); fileManifest.push({ path: relative(ROOT, path), bytes: buf.length, sha256: sha256(buf) });
  }
  await saveJson('MANIFEST.json', {
    schema: 'NEXUS_T0A_EXACT_SCOPE_OFFICIAL_REACQUISITION_MANIFEST_V1',
    datasetVersion: 'nexus-t0a-official-lineup-participation-reacquired-v1',
    byteIdentityClaimToExpiredArtifacts: false,
    capturedAt, sourceAuthority: 'Lega Serie A Sports Data Platform / Opta', base: BASE, competitionId: COMPETITION_ID,
    historicalPin: HISTORICAL_PIN, historicalNormalizerVersion: NORMALIZER_PIN, minutesConvention: MINUTES_CONVENTION,
    coverage, files: fileManifest,
    rules: ['GET_ONLY','NO_ABSENCE_TO_DNP','EXACT_SOURCE_IDENTITY_NO_FUZZY','INCOMPLETE_MATCH_FAIL_CLOSED','UNKNOWN_NULL_WHEN_NOT_OBSERVABLE']
  });
  console.log(JSON.stringify({ status: 'ACQUISITION_COMPLETE', coverage }, null, 2));
}
main().catch((e) => { console.error(e); process.exitCode = 1; });
