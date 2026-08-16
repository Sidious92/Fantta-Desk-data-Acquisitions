import fs from 'node:fs/promises';
import path from 'node:path';

const DOMESTIC_PATH = 'data/frozen/domestic-strength-foreign-v0/fantanexus_domestic_strength_foreign_raw_2021_2026_v0.json';
const UEFA_PATH = 'data/frozen/uefa-club-coefficients-v0/fantanexus_uefa_club_coefficients_2021_2026_v0.json';
const OUT_DIR = '.nexus-club-identity-v0/probe';

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

function levenshtein(a, b) {
  if (a === b) return 0;
  if (!a.length) return b.length;
  if (!b.length) return a.length;
  let prev = Array.from({ length: b.length + 1 }, (_, i) => i);
  for (let i = 1; i <= a.length; i += 1) {
    const curr = [i];
    for (let j = 1; j <= b.length; j += 1) {
      curr[j] = Math.min(
        curr[j - 1] + 1,
        prev[j] + 1,
        prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1),
      );
    }
    prev = curr;
  }
  return prev[b.length];
}

function tokenSet(value) {
  return new Set(normalizeSurface(value).split(' ').filter(Boolean));
}

function jaccard(a, b) {
  const A = tokenSet(a);
  const B = tokenSet(b);
  const union = new Set([...A, ...B]);
  if (!union.size) return 0;
  let intersection = 0;
  for (const token of A) if (B.has(token)) intersection += 1;
  return intersection / union.size;
}

function similarity(a, b) {
  const na = normalizeSurface(a);
  const nb = normalizeSurface(b);
  if (!na || !nb) return 0;
  if (na === nb) return 1;
  const edit = 1 - levenshtein(na, nb) / Math.max(na.length, nb.length);
  const token = jaccard(na, nb);
  const containment = na.includes(nb) || nb.includes(na) ? Math.min(na.length, nb.length) / Math.max(na.length, nb.length) : 0;
  return Math.max(edit, token, containment);
}

function snapshotYearForSeason(season) {
  const match = String(season).match(/^(\d{4})-\d{2}$/);
  if (!match) throw new Error(`Unsupported domestic season: ${season}`);
  return Number(match[1]);
}

async function main() {
  const domestic = JSON.parse(await fs.readFile(DOMESTIC_PATH, 'utf8'));
  const uefa = JSON.parse(await fs.readFile(UEFA_PATH, 'utf8'));

  const byKey = new Map();
  for (const row of uefa) {
    const key = `${row.snapshot_year}|${row.association_code}`;
    if (!byKey.has(key)) byKey.set(key, []);
    byKey.get(key).push(row);
  }

  const rowResults = [];
  for (const row of domestic) {
    const snapshotYear = snapshotYearForSeason(row.season);
    const candidates = byKey.get(`${snapshotYear}|${row.association_code}`) ?? [];
    const domesticNorm = normalizeSurface(row.team);
    const exact = candidates.find((candidate) => normalizeSurface(candidate.club) === domesticNorm);

    if (exact) {
      rowResults.push({
        season: row.season,
        snapshot_year: snapshotYear,
        association_code: row.association_code,
        competition: row.competition,
        domestic_team: row.team,
        domestic_normalized: domesticNorm,
        status: 'MATCHED_EXACT_SURFACE',
        matched_uefa_club: exact.club,
        matched_uefa_club_key: exact.club_key,
        candidate_score: 1,
        review_candidates: [],
      });
      continue;
    }

    const ranked = candidates
      .map((candidate) => ({
        club: candidate.club,
        club_key: candidate.club_key,
        score: similarity(row.team, candidate.club),
        coefficient_5y: candidate.coefficient_5y,
        club_points_5y: candidate.club_points_5y,
      }))
      .sort((a, b) => b.score - a.score || b.coefficient_5y - a.coefficient_5y || a.club.localeCompare(b.club, 'en'))
      .slice(0, 5);

    rowResults.push({
      season: row.season,
      snapshot_year: snapshotYear,
      association_code: row.association_code,
      competition: row.competition,
      domestic_team: row.team,
      domestic_normalized: domesticNorm,
      status: 'REVIEW_REQUIRED',
      matched_uefa_club: null,
      matched_uefa_club_key: null,
      candidate_score: ranked[0]?.score ?? 0,
      review_candidates: ranked,
    });
  }

  const uniqueReviewMap = new Map();
  for (const row of rowResults.filter((item) => item.status === 'REVIEW_REQUIRED')) {
    const key = `${row.association_code}|${row.domestic_team}`;
    if (!uniqueReviewMap.has(key)) {
      uniqueReviewMap.set(key, {
        association_code: row.association_code,
        domestic_team: row.domestic_team,
        domestic_normalized: row.domestic_normalized,
        seasons: [],
        observations: [],
      });
    }
    const item = uniqueReviewMap.get(key);
    item.seasons.push(row.season);
    item.observations.push({
      season: row.season,
      snapshot_year: row.snapshot_year,
      top_candidates: row.review_candidates,
    });
  }

  const uniqueReview = [...uniqueReviewMap.values()].map((item) => {
    const aggregate = new Map();
    for (const observation of item.observations) {
      for (const candidate of observation.top_candidates) {
        if (!aggregate.has(candidate.club)) {
          aggregate.set(candidate.club, { club: candidate.club, appearances: 0, max_score: 0, mean_score_sum: 0 });
        }
        const entry = aggregate.get(candidate.club);
        entry.appearances += 1;
        entry.max_score = Math.max(entry.max_score, candidate.score);
        entry.mean_score_sum += candidate.score;
      }
    }
    const aggregateCandidates = [...aggregate.values()]
      .map((entry) => ({
        club: entry.club,
        snapshot_appearances: entry.appearances,
        max_score: entry.max_score,
        mean_score: entry.mean_score_sum / entry.appearances,
      }))
      .sort((a, b) => b.max_score - a.max_score || b.snapshot_appearances - a.snapshot_appearances || b.mean_score - a.mean_score)
      .slice(0, 8);
    return {
      association_code: item.association_code,
      domestic_team: item.domestic_team,
      domestic_normalized: item.domestic_normalized,
      seasons: [...new Set(item.seasons)],
      aggregate_candidates: aggregateCandidates,
      observations: item.observations,
    };
  }).sort((a, b) => a.association_code.localeCompare(b.association_code) || a.domestic_team.localeCompare(b.domestic_team, 'en'));

  const exactRows = rowResults.filter((row) => row.status === 'MATCHED_EXACT_SURFACE').length;
  const reviewRows = rowResults.length - exactRows;
  const audit = {
    dataset: 'FantaNexus Club Identity Probe v0',
    status: reviewRows ? 'REVIEW_REQUIRED' : 'PASS_EXACT',
    generated_at: new Date().toISOString(),
    input: {
      domestic_dataset: DOMESTIC_PATH,
      uefa_dataset: UEFA_PATH,
      domestic_rows: domestic.length,
      uefa_rows: uefa.length,
    },
    policy: {
      automatic_match: 'same snapshot year + same association + exact normalized surface only',
      normalization: 'NFKD diacritics removal, lowercase, ampersand->and, punctuation/whitespace collapse',
      fuzzy_policy: 'similarity is recommendation-only; it never creates an identity mapping',
      no_uefa_history_policy: 'not assigned by this probe; unresolved exact misses must be reviewed before distinguishing aliases from true no-history clubs',
    },
    domestic_rows: rowResults.length,
    exact_rows: exactRows,
    review_rows: reviewRows,
    exact_rate: rowResults.length ? exactRows / rowResults.length : null,
    unique_review_identities: uniqueReview.length,
    by_association: Object.fromEntries([...new Set(rowResults.map((row) => row.association_code))].sort().map((association) => {
      const rows = rowResults.filter((row) => row.association_code === association);
      const exact = rows.filter((row) => row.status === 'MATCHED_EXACT_SURFACE').length;
      return [association, { rows: rows.length, exact_rows: exact, review_rows: rows.length - exact }];
    })),
  };

  await fs.mkdir(OUT_DIR, { recursive: true });
  await fs.writeFile(path.join(OUT_DIR, 'fantanexus_club_identity_probe_v0_rows.json'), JSON.stringify(rowResults, null, 2) + '\n');
  await fs.writeFile(path.join(OUT_DIR, 'fantanexus_club_identity_probe_v0_review.json'), JSON.stringify(uniqueReview, null, 2) + '\n');
  await fs.writeFile(path.join(OUT_DIR, 'fantanexus_club_identity_probe_v0_audit.json'), JSON.stringify(audit, null, 2) + '\n');

  process.stderr.write(`Identity probe: ${exactRows}/${rowResults.length} exact rows; ${reviewRows} review rows; ${uniqueReview.length} unique identities require review.\n`);
}

await main();
