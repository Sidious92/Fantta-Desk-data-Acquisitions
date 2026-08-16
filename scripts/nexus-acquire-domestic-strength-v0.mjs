import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const SEASONS = ['2021-22', '2022-23', '2023-24', '2024-25', '2025-26'];
const OUT_DIR = '.nexus-domestic-strength-v0/acquisition';

// Foreign-league v0 only. Italy is intentionally not re-acquired here because the
// private Nexus repository already has a separately audited Serie A + Serie B match
// freeze, including an official Lega B supplement for 2025/26.
//
// This public acquisition surface is restricted to straight-table winter leagues
// with complete, auditable regular-season match ledgers. Split/halved-points and
// summer-calendar competitions require dedicated rules-aware adapters later.
const TARGETS = [
  { association: 'ENG', country: 'England', competition: 'Premier League', repo: 'openfootball/england', mode: 'season-dir', level: 1 },
  { association: 'GER', country: 'Germany', competition: 'Bundesliga', repo: 'openfootball/deutschland', mode: 'season-dir', level: 1 },
  { association: 'ESP', country: 'Spain', competition: 'La Liga', repo: 'openfootball/espana', mode: 'season-dir', level: 1 },
  { association: 'FRA', country: 'France', competition: 'Ligue 1', repo: 'openfootball/europe', mode: 'flat-country', countryPath: 'france', level: 1 },
  { association: 'POR', country: 'Portugal', competition: 'Primeira Liga', repo: 'openfootball/europe', mode: 'flat-country', countryPath: 'portugal', level: 1 },
  { association: 'NED', country: 'Netherlands', competition: 'Eredivisie', repo: 'openfootball/europe', mode: 'flat-country', countryPath: 'netherlands', level: 1 },
];

const SUPPLEMENTS = [
  {
    association: 'NED',
    competition: 'Eredivisie',
    season: '2025-26',
    home: 'NAC Breda',
    away: 'SC Heerenveen',
    homeGoals: 2,
    awayGoals: 0,
    source: 'NAC Breda official',
    source_ref: 'https://www.nac.nl/nieuws/winst-in-twee-delen-voor-gedegradeerd-nac',
    evidence_tokens: ['Heerenveen', '2-0'],
    reason: 'OpenFootball snapshot marks the round-33 fixture cancelled after the 82nd-minute stoppage; the official club source records the completed remainder on 2026-05-11 and final 2-0 result.',
  },
];

const githubHeaders = {
  accept: 'application/vnd.github+json',
  'user-agent': 'FantaNexus/0.1 domestic-strength-acquisition',
  ...(process.env.GITHUB_TOKEN ? { authorization: `Bearer ${process.env.GITHUB_TOKEN}` } : {}),
};

function sha256(text) {
  return crypto.createHash('sha256').update(text).digest('hex');
}

async function fetchJson(url) {
  const res = await fetch(url, { headers: githubHeaders });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${url}`);
  return res.json();
}

async function fetchText(url) {
  let lastError;
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    try {
      const res = await fetch(url, { headers: { 'user-agent': githubHeaders['user-agent'] } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.text();
    } catch (err) {
      lastError = err;
      if (attempt < 4) await new Promise((resolve) => setTimeout(resolve, attempt * 700));
    }
  }
  throw new Error(`Failed to fetch ${url}: ${lastError?.message ?? lastError}`);
}

function chooseFile(entries, target, season) {
  const files = entries.filter((entry) => entry.type === 'file' && entry.name.endsWith('.txt'));
  let candidates;
  if (target.mode === 'season-dir') {
    candidates = files.filter((entry) =>
      entry.name.startsWith(`${target.level}-`) &&
      !entry.name.includes('-full') &&
      !entry.name.toLowerCase().includes('cup')
    );
  } else {
    const seasonPrefix = `${season}_`;
    const levelPattern = new RegExp(`${target.level}\\.txt$`, 'i');
    candidates = files.filter((entry) =>
      entry.name.startsWith(seasonPrefix) &&
      levelPattern.test(entry.name) &&
      !entry.name.toLowerCase().includes('cup')
    );
  }
  if (candidates.length !== 1) {
    throw new Error(`${target.association} ${target.competition} ${season}: expected 1 source file, found ${candidates.length}: ${candidates.map((x) => x.name).join(', ')}`);
  }
  return candidates[0];
}

async function discoverSource(target, season) {
  const apiPath = target.mode === 'season-dir'
    ? `https://api.github.com/repos/${target.repo}/contents/${season}?ref=master`
    : `https://api.github.com/repos/${target.repo}/contents/${target.countryPath}?ref=master`;
  const entries = await fetchJson(apiPath);
  const file = chooseFile(entries, target, season);
  return {
    repository: target.repo,
    git_blob_sha: file.sha,
    source_ref: file.html_url,
    download_url: file.download_url,
    source_path: file.path,
  };
}

function parseHeaderNumber(text, label) {
  const patterns = {
    teams: /^#\s*Teams?\s+(\d+)\s*$/im,
    matches: /^#\s*Matches?\s+(\d+)\s*$/im,
  };
  const match = text.match(patterns[label]);
  return match ? Number(match[1]) : null;
}

function parseRegularSeasonStageMatches(text) {
  const match = text.match(/^#\s*Stages?[^\n]*Regular Season\s*\((\d+)\)/im);
  return match ? Number(match[1]) : null;
}

function cleanTeam(value) {
  return value.replace(/\s+/g, ' ').trim();
}

function parseMatchLine(line) {
  // Format A: Team A v Team B 2-1 (1-0), optionally with a trailing [awarded] tag.
  let match = line.match(/^\s*(?:\d{1,2}:\d{2}\s+)?(.+?)\s+v\s+(.+?)\s+(\d+)-(\d+)(?:\s+\([^)]*\))?(?:\s+\[[^\]]+\])?\s*$/i);
  if (match) {
    return {
      home: cleanTeam(match[1]),
      away: cleanTeam(match[2]),
      homeGoals: Number(match[3]),
      awayGoals: Number(match[4]),
      annotation: /\[awarded\]/i.test(line) ? 'awarded' : null,
    };
  }

  // If a line contains the explicit separator but no numeric final score (for
  // example [cancelled]), it is not a completed match and must not fall through
  // to the alternate parser.
  if (/\s+v\s+/i.test(line)) return null;

  // Format B: Team A 2-1 (1-0) Team B.
  match = line.match(/^\s*(?:\d{1,2}:\d{2}\s+)?(.+?)\s+(\d+)-(\d+)(?:\s+\([^)]*\))?\s+(.+?)\s*$/);
  if (match) {
    const home = cleanTeam(match[1]);
    const away = cleanTeam(match[4]);
    if (/\[awarded\]/i.test(home) || /\[awarded\]/i.test(away)) return null;
    return { home, away, homeGoals: Number(match[2]), awayGoals: Number(match[3]), annotation: null };
  }
  return null;
}

function parseMatches(text, regularSeasonExpected) {
  const parsed = [];
  for (const line of text.split(/\r?\n/)) {
    const match = parseMatchLine(line);
    if (!match) continue;
    if (!match.home || !match.away || match.home === match.away) continue;
    parsed.push(match);
    // For multi-stage files, Regular Season is listed first. Stop exactly at the
    // source-declared regular-season match count so promotion/relegation playoffs
    // cannot leak into the domestic-strength table.
    if (regularSeasonExpected !== null && parsed.length === regularSeasonExpected) break;
  }
  return parsed;
}

async function applyVerifiedSupplements(target, season, matches, expectedMatches) {
  const provenance = [];
  const candidates = SUPPLEMENTS.filter((item) =>
    item.association === target.association &&
    item.competition === target.competition &&
    item.season === season
  );

  for (const supplement of candidates) {
    const alreadyPresent = matches.some((m) =>
      m.home === supplement.home && m.away === supplement.away &&
      m.homeGoals === supplement.homeGoals && m.awayGoals === supplement.awayGoals
    );
    if (alreadyPresent) continue;
    if (expectedMatches !== null && matches.length >= expectedMatches) continue;

    const evidence = await fetchText(supplement.source_ref);
    const evidenceText = evidence.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
    const verified = supplement.evidence_tokens.every((token) => evidenceText.toLowerCase().includes(token.toLowerCase()));
    if (!verified) {
      throw new Error(`${target.association} ${target.competition} ${season}: supplement evidence verification failed for ${supplement.source_ref}`);
    }

    matches.push({
      home: supplement.home,
      away: supplement.away,
      homeGoals: supplement.homeGoals,
      awayGoals: supplement.awayGoals,
      annotation: 'verified_supplement',
    });
    provenance.push({
      home: supplement.home,
      away: supplement.away,
      home_goals: supplement.homeGoals,
      away_goals: supplement.awayGoals,
      source: supplement.source,
      source_ref: supplement.source_ref,
      evidence_sha256: sha256(evidence),
      reason: supplement.reason,
    });
  }
  return provenance;
}

function assignPpgPercentiles(rows) {
  const sorted = [...rows].sort((a, b) => b.points_per_game - a.points_per_game || a.team.localeCompare(b.team, 'en'));
  const n = sorted.length;
  let i = 0;
  while (i < n) {
    let j = i;
    while (j + 1 < n && Math.abs(sorted[j + 1].points_per_game - sorted[i].points_per_game) < 1e-12) j += 1;
    const averageIndex = (i + j) / 2;
    const percentile = n <= 1 ? null : (n - 1 - averageIndex) / (n - 1);
    for (let k = i; k <= j; k += 1) sorted[k].ppg_percentile = percentile;
    i = j + 1;
  }
}

function buildTable(matches) {
  const teams = new Map();
  const get = (name) => {
    if (!teams.has(name)) {
      teams.set(name, { team: name, played: 0, wins: 0, draws: 0, losses: 0, goals_for: 0, goals_against: 0, points: 0 });
    }
    return teams.get(name);
  };

  for (const match of matches) {
    const home = get(match.home);
    const away = get(match.away);
    home.played += 1;
    away.played += 1;
    home.goals_for += match.homeGoals;
    home.goals_against += match.awayGoals;
    away.goals_for += match.awayGoals;
    away.goals_against += match.homeGoals;
    if (match.homeGoals > match.awayGoals) {
      home.wins += 1; home.points += 3; away.losses += 1;
    } else if (match.homeGoals < match.awayGoals) {
      away.wins += 1; away.points += 3; home.losses += 1;
    } else {
      home.draws += 1; away.draws += 1; home.points += 1; away.points += 1;
    }
  }

  const rows = [...teams.values()].map((row) => ({
    ...row,
    goal_difference: row.goals_for - row.goals_against,
    points_per_game: row.played ? row.points / row.played : null,
    goal_difference_per_game: row.played ? (row.goals_for - row.goals_against) / row.played : null,
    ppg_percentile: null,
  }));
  assignPpgPercentiles(rows);
  rows.sort((a, b) => b.points_per_game - a.points_per_game || b.goal_difference_per_game - a.goal_difference_per_game || a.team.localeCompare(b.team, 'en'));
  return rows;
}

function auditGroup({ target, season, headerTeams, headerMatches, regularSeasonStageMatches, expectedMatches, matches, table, source, supplements }) {
  const totalGf = table.reduce((sum, row) => sum + row.goals_for, 0);
  const totalGa = table.reduce((sum, row) => sum + row.goals_against, 0);
  const games = table.map((row) => row.played);
  const failures = [];
  if (headerTeams === null) failures.push('missing_header_teams');
  if (expectedMatches === null) failures.push('missing_expected_match_count');
  if (headerTeams !== null && table.length !== headerTeams) failures.push('team_count_mismatch');
  if (expectedMatches !== null && matches.length !== expectedMatches) failures.push('match_count_mismatch');
  if (games.length && Math.min(...games) !== Math.max(...games)) failures.push('unequal_games_played');
  if (totalGf !== totalGa) failures.push('goals_balance_mismatch');
  if (table.some((row) => row.played !== row.wins + row.draws + row.losses)) failures.push('wdl_algebra_mismatch');
  if (table.some((row) => row.points !== row.wins * 3 + row.draws)) failures.push('points_algebra_mismatch');
  if (table.some((row) => !Number.isFinite(row.points_per_game) || !Number.isFinite(row.goal_difference_per_game) || !Number.isFinite(row.ppg_percentile))) failures.push('nonfinite_metric');
  if (table.some((row) => row.ppg_percentile < -1e-12 || row.ppg_percentile > 1 + 1e-12)) failures.push('percentile_out_of_range');

  return {
    association: target.association,
    country: target.country,
    competition: target.competition,
    season,
    source_path: source.source_path,
    source_git_blob_sha: source.git_blob_sha,
    header_teams: headerTeams,
    parsed_teams: table.length,
    header_matches: headerMatches,
    regular_season_stage_matches: regularSeasonStageMatches,
    expected_matches: expectedMatches,
    parsed_matches: matches.length,
    min_matches_per_team: games.length ? Math.min(...games) : null,
    max_matches_per_team: games.length ? Math.max(...games) : null,
    supplements: supplements.length,
    status: failures.length ? 'FAIL' : 'PASS',
    failures,
  };
}

function csvEscape(value) {
  if (value === null || value === undefined) return '';
  const s = String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

function toCsv(rows) {
  const cols = [
    'season','association_code','country','competition','competition_level','team','league_size',
    'played','wins','draws','losses','goals_for','goals_against','goal_difference','points',
    'points_per_game','goal_difference_per_game','ppg_percentile','percentile_basis','table_basis',
    'source','source_ref','source_path','source_git_blob_sha','source_file_sha256'
  ];
  return [cols.join(','), ...rows.map((row) => cols.map((col) => csvEscape(row[col])).join(','))].join('\n') + '\n';
}

async function main() {
  const allRows = [];
  const groups = [];
  const sourceFiles = [];
  const allSupplements = [];

  for (const target of TARGETS) {
    for (const season of SEASONS) {
      process.stderr.write(`Acquire ${target.association} ${target.competition} ${season}...\n`);
      try {
        const source = await discoverSource(target, season);
        const text = await fetchText(source.download_url);
        const fileSha256 = sha256(text);
        const headerTeams = parseHeaderNumber(text, 'teams');
        const headerMatches = parseHeaderNumber(text, 'matches');
        const regularSeasonStageMatches = parseRegularSeasonStageMatches(text);
        const expectedMatches = regularSeasonStageMatches ?? headerMatches;
        const matches = parseMatches(text, regularSeasonStageMatches);
        const supplements = await applyVerifiedSupplements(target, season, matches, expectedMatches);
        allSupplements.push(...supplements.map((item) => ({ association: target.association, competition: target.competition, season, ...item })));
        const table = buildTable(matches);
        const groupAudit = auditGroup({ target, season, headerTeams, headerMatches, regularSeasonStageMatches, expectedMatches, matches, table, source, supplements });
        groups.push(groupAudit);
        sourceFiles.push({
          association: target.association,
          competition: target.competition,
          season,
          repository: source.repository,
          source_path: source.source_path,
          source_ref: source.source_ref,
          source_git_blob_sha: source.git_blob_sha,
          source_file_sha256: fileSha256,
        });
        for (const row of table) {
          allRows.push({
            season,
            association_code: target.association,
            country: target.country,
            competition: target.competition,
            competition_level: target.level,
            team: row.team,
            league_size: table.length,
            played: row.played,
            wins: row.wins,
            draws: row.draws,
            losses: row.losses,
            goals_for: row.goals_for,
            goals_against: row.goals_against,
            goal_difference: row.goal_difference,
            points: row.points,
            points_per_game: row.points_per_game,
            goal_difference_per_game: row.goal_difference_per_game,
            ppg_percentile: row.ppg_percentile,
            percentile_basis: 'within_competition_season_ppg_tie_averaged',
            table_basis: 'completed_regular_season_match_results_3_1_0',
            source: source.repository,
            source_ref: source.source_ref,
            source_path: source.source_path,
            source_git_blob_sha: source.git_blob_sha,
            source_file_sha256: fileSha256,
          });
        }
        process.stderr.write(`  ${groupAudit.status}: ${matches.length} matches, ${table.length} teams${supplements.length ? `, ${supplements.length} verified supplement` : ''}\n`);
      } catch (err) {
        groups.push({
          association: target.association,
          country: target.country,
          competition: target.competition,
          season,
          status: 'FAIL',
          failures: ['source_acquisition_error'],
          error: err.message,
        });
        process.stderr.write(`  FAIL: ${err.message}\n`);
      }
    }
  }

  const duplicateKeys = [];
  const seen = new Set();
  for (const row of allRows) {
    const key = `${row.season}|${row.association_code}|${row.competition}|${row.team}`;
    if (seen.has(key)) duplicateKeys.push(key); else seen.add(key);
  }

  const failedGroups = groups.filter((group) => group.status !== 'PASS');
  const audit = {
    dataset: 'FantaNexus Domestic Strength Foreign Raw v0',
    status: failedGroups.length || duplicateKeys.length ? 'FAIL' : 'PASS',
    generated_at: new Date().toISOString(),
    policy: {
      seasons: SEASONS,
      scope: 'foreign straight-table winter top divisions only; Italy remains sourced from the separately frozen private Serie A + Serie B ledger',
      associations: TARGETS.map((target) => target.association),
      metrics: ['points_per_game', 'goal_difference_per_game', 'ppg_percentile'],
      ppg_percentile_definition: 'within competition-season percentile of points_per_game, top=1 bottom=0, exact PPG ties receive their average percentile',
      rationale: 'PPG percentile is competition-rule-neutral and avoids inventing official finishing-order tie-breakers during raw acquisition.',
      excluded_from_v0: ['split/halved-points competitions', 'summer-calendar leagues', 'foreign second divisions', 'competitions without five-season complete source coverage'],
    },
    rows: allRows.length,
    groups_expected: TARGETS.length * SEASONS.length,
    groups_pass: groups.length - failedGroups.length,
    groups_fail: failedGroups.length,
    verified_supplements: allSupplements,
    duplicate_team_season_keys: duplicateKeys.length,
    duplicate_examples: duplicateKeys.slice(0, 25),
    groups,
  };

  await fs.mkdir(OUT_DIR, { recursive: true });
  const jsonPath = path.join(OUT_DIR, 'fantanexus_domestic_strength_foreign_raw_2021_2026_v0.json');
  const csvPath = path.join(OUT_DIR, 'fantanexus_domestic_strength_foreign_raw_2021_2026_v0.csv');
  const auditPath = path.join(OUT_DIR, 'fantanexus_domestic_strength_foreign_raw_2021_2026_v0_audit.json');
  const manifestPath = path.join(OUT_DIR, 'fantanexus_domestic_strength_foreign_raw_2021_2026_v0_manifest.json');

  const jsonText = JSON.stringify(allRows, null, 2) + '\n';
  const csvText = toCsv(allRows);
  const auditText = JSON.stringify(audit, null, 2) + '\n';
  const manifest = {
    dataset: 'fantanexus_domestic_strength_foreign_raw_2021_2026_v0',
    status: audit.status,
    generated_at: new Date().toISOString(),
    seasons: SEASONS,
    associations: TARGETS.map((target) => target.association),
    competitions: TARGETS.map((target) => `${target.association}:${target.competition}`),
    rows: allRows.length,
    source_files: sourceFiles,
    verified_supplements: allSupplements,
    files: {
      json: { path: jsonPath, sha256: sha256(jsonText) },
      csv: { path: csvPath, sha256: sha256(csvText) },
      audit: { path: auditPath, sha256: sha256(auditText) },
    },
  };

  await fs.writeFile(jsonPath, jsonText);
  await fs.writeFile(csvPath, csvText);
  await fs.writeFile(auditPath, auditText);
  await fs.writeFile(manifestPath, JSON.stringify(manifest, null, 2) + '\n');

  process.stderr.write(`Domestic strength audit: ${audit.status} (${audit.groups_pass}/${audit.groups_expected} groups PASS)\n`);
  if (audit.status !== 'PASS') process.exitCode = 1;
}

await main();
