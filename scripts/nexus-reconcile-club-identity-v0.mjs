import fs from 'node:fs/promises';
import path from 'node:path';

const DOMESTIC_PATH = 'data/frozen/domestic-strength-foreign-v0/fantanexus_domestic_strength_foreign_raw_2021_2026_v0.json';
const UEFA_PATH = 'data/frozen/uefa-club-coefficients-v0/fantanexus_uefa_club_coefficients_2021_2026_v0.json';
const ALIAS_PATH = 'data/mappings/club-identity-domestic-to-uefa-v0.json';
const OUT_DIR = '.nexus-club-identity-v0/reconciliation';

function normalizeSurface(value) {
  return String(value ?? '')
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function snapshotYearForSeason(season) {
  const match = String(season).match(/^(\d{4})-\d{2}$/);
  if (!match) throw new Error(`Unsupported season ${season}`);
  return Number(match[1]);
}

function levenshtein(a, b) {
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i += 1) {
    const curr = [i];
    for (let j = 1; j <= b.length; j += 1) {
      curr[j] = Math.min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = curr;
  }
  return prev[b.length];
}

function similarity(a, b) {
  const A = normalizeSurface(a);
  const B = normalizeSurface(b);
  if (!A || !B) return 0;
  if (A === B) return 1;
  const edit = 1 - levenshtein(A, B) / Math.max(A.length, B.length);
  const ta = new Set(A.split(' '));
  const tb = new Set(B.split(' '));
  const union = new Set([...ta, ...tb]);
  let inter = 0;
  for (const token of ta) if (tb.has(token)) inter += 1;
  const jaccard = union.size ? inter / union.size : 0;
  const containment = A.includes(B) || B.includes(A) ? Math.min(A.length, B.length) / Math.max(A.length, B.length) : 0;
  return Math.max(edit, jaccard, containment);
}

async function main() {
  const domestic = JSON.parse(await fs.readFile(DOMESTIC_PATH, 'utf8'));
  const uefa = JSON.parse(await fs.readFile(UEFA_PATH, 'utf8'));
  const aliasRegistry = JSON.parse(await fs.readFile(ALIAS_PATH, 'utf8'));

  const aliases = new Map();
  const allUefaTargets = new Map();
  for (const row of uefa) {
    const key = `${row.association_code}|${row.club}`;
    allUefaTargets.set(key, true);
  }

  const aliasErrors = [];
  for (const alias of aliasRegistry.aliases) {
    const key = `${alias.association_code}|${alias.domestic_team}`;
    if (aliases.has(key)) aliasErrors.push(`duplicate alias ${key}`);
    aliases.set(key, alias.uefa_club);
    if (!allUefaTargets.has(`${alias.association_code}|${alias.uefa_club}`)) {
      aliasErrors.push(`target absent from frozen UEFA dataset: ${key} -> ${alias.uefa_club}`);
    }
  }
  if (aliasErrors.length) throw new Error(aliasErrors.join('\n'));

  const bySnapshotAssociation = new Map();
  for (const row of uefa) {
    const key = `${row.snapshot_year}|${row.association_code}`;
    if (!bySnapshotAssociation.has(key)) bySnapshotAssociation.set(key, []);
    bySnapshotAssociation.get(key).push(row);
  }

  const rows = [];
  for (const domesticRow of domestic) {
    const snapshotYear = snapshotYearForSeason(domesticRow.season);
    const candidates = bySnapshotAssociation.get(`${snapshotYear}|${domesticRow.association_code}`) ?? [];
    const exact = candidates.find((item) => normalizeSurface(item.club) === normalizeSurface(domesticRow.team));
    const aliasTarget = aliases.get(`${domesticRow.association_code}|${domesticRow.team}`) ?? null;
    const aliasMatch = aliasTarget ? candidates.find((item) => item.club === aliasTarget) : null;

    if (exact) {
      rows.push({
        season: domesticRow.season,
        snapshot_year: snapshotYear,
        association_code: domesticRow.association_code,
        competition: domesticRow.competition,
        domestic_team: domesticRow.team,
        status: 'MATCHED',
        match_method: 'EXACT_NORMALIZED_SURFACE',
        uefa_club: exact.club,
        uefa_club_key: exact.club_key,
        coefficient_5y: exact.coefficient_5y,
        club_points_5y: exact.club_points_5y,
        uses_association_floor: exact.uses_association_floor,
      });
      continue;
    }

    if (aliasMatch) {
      rows.push({
        season: domesticRow.season,
        snapshot_year: snapshotYear,
        association_code: domesticRow.association_code,
        competition: domesticRow.competition,
        domestic_team: domesticRow.team,
        status: 'MATCHED',
        match_method: 'REVIEWED_ALIAS',
        uefa_club: aliasMatch.club,
        uefa_club_key: aliasMatch.club_key,
        coefficient_5y: aliasMatch.coefficient_5y,
        club_points_5y: aliasMatch.club_points_5y,
        uses_association_floor: aliasMatch.uses_association_floor,
      });
      continue;
    }

    if (aliasTarget && !aliasMatch) {
      // The identity relation is reviewed, but this club has no row in this
      // preseason UEFA coefficient snapshot. That is true no-history for this
      // snapshot, not an unresolved name match.
      rows.push({
        season: domesticRow.season,
        snapshot_year: snapshotYear,
        association_code: domesticRow.association_code,
        competition: domesticRow.competition,
        domestic_team: domesticRow.team,
        status: 'NO_UEFA_HISTORY',
        match_method: 'REVIEWED_ALIAS_TARGET_ABSENT_IN_SNAPSHOT',
        uefa_club: aliasTarget,
        uefa_club_key: null,
        coefficient_5y: null,
        club_points_5y: null,
        uses_association_floor: null,
      });
      continue;
    }

    const ranked = candidates
      .map((candidate) => ({ club: candidate.club, score: similarity(domesticRow.team, candidate.club) }))
      .sort((a, b) => b.score - a.score || a.club.localeCompare(b.club, 'en'))
      .slice(0, 5);

    rows.push({
      season: domesticRow.season,
      snapshot_year: snapshotYear,
      association_code: domesticRow.association_code,
      competition: domesticRow.competition,
      domestic_team: domesticRow.team,
      status: 'REVIEW_REQUIRED',
      match_method: null,
      uefa_club: null,
      uefa_club_key: null,
      coefficient_5y: null,
      club_points_5y: null,
      uses_association_floor: null,
      review_candidates: ranked,
    });
  }

  const reviewGroups = new Map();
  for (const row of rows.filter((item) => item.status === 'REVIEW_REQUIRED')) {
    const key = `${row.association_code}|${row.domestic_team}`;
    if (!reviewGroups.has(key)) reviewGroups.set(key, { association_code: row.association_code, domestic_team: row.domestic_team, seasons: [], candidates_by_season: [] });
    const group = reviewGroups.get(key);
    group.seasons.push(row.season);
    group.candidates_by_season.push({ season: row.season, candidates: row.review_candidates });
  }

  const unresolved = [...reviewGroups.values()].sort((a, b) => a.association_code.localeCompare(b.association_code) || a.domestic_team.localeCompare(b.domestic_team, 'en'));
  const counts = Object.fromEntries(['MATCHED','NO_UEFA_HISTORY','REVIEW_REQUIRED'].map((status) => [status, rows.filter((row) => row.status === status).length]));
  const methods = {};
  for (const row of rows.filter((item) => item.status === 'MATCHED')) methods[row.match_method] = (methods[row.match_method] ?? 0) + 1;

  const audit = {
    dataset: 'FantaNexus Club Identity Reconciliation v0',
    status: counts.REVIEW_REQUIRED ? 'REVIEW_REQUIRED' : 'PASS',
    generated_at: new Date().toISOString(),
    inputs: {
      domestic: DOMESTIC_PATH,
      uefa: UEFA_PATH,
      aliases: ALIAS_PATH,
      domestic_rows: domestic.length,
      uefa_rows: uefa.length,
      reviewed_aliases: aliasRegistry.aliases.length,
    },
    policy: {
      automatic_match: 'same snapshot + same association + exact normalized surface only',
      alias_match: 'explicit reviewed alias registry only',
      no_uefa_history: 'assigned automatically only when a reviewed alias target exists globally but is absent from the relevant snapshot; all other misses remain REVIEW_REQUIRED',
      fuzzy_candidates: 'diagnostic only and never promoted automatically',
    },
    rows: rows.length,
    counts,
    matched_methods: methods,
    unique_unresolved_identities: unresolved.length,
    by_association: Object.fromEntries([...new Set(rows.map((row) => row.association_code))].sort().map((association) => {
      const subset = rows.filter((row) => row.association_code === association);
      return [association, Object.fromEntries(['MATCHED','NO_UEFA_HISTORY','REVIEW_REQUIRED'].map((status) => [status, subset.filter((row) => row.status === status).length]))];
    })),
  };

  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.writeFile(path.join(OUT_DIR, 'fantanexus_club_identity_reconciliation_v0_rows.json'), JSON.stringify(rows, null, 2) + '\n');
  await fs.writeFile(path.join(OUT_DIR, 'fantanexus_club_identity_reconciliation_v0_unresolved.json'), JSON.stringify(unresolved, null, 2) + '\n');
  await fs.writeFile(path.join(OUT_DIR, 'fantanexus_club_identity_reconciliation_v0_audit.json'), JSON.stringify(audit, null, 2) + '\n');

  process.stderr.write(`Reconciliation: ${counts.MATCHED} MATCHED, ${counts.NO_UEFA_HISTORY} NO_UEFA_HISTORY, ${counts.REVIEW_REQUIRED} REVIEW_REQUIRED (${unresolved.length} unique).\n`);
}

await main();
