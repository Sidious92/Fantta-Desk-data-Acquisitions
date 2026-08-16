import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const SEASONS = ['2021-22', '2022-23', '2023-24', '2024-25', '2025-26'];
const OUT_DIR = '.nexus-domestic-strength-v0/acquisition';

// v0 deliberately starts with straight-table winter leagues where a match-derived
// 3/1/0 table is a faithful sporting summary. Split/halved-points leagues are held
// out for a later rules-aware expansion rather than silently approximated.
const TARGETS = [
  { association: 'ENG', country: 'England', competition: 'Premier League', repo: 'openfootball/england', mode: 'season-dir', level: 1 },
  { association: 'GER', country: 'Germany', competition: 'Bundesliga', repo: 'openfootball/deutschland', mode: 'season-dir', level: 1 },
  { association: 'ESP', country: 'Spain', competition: 'La Liga', repo: 'openfootball/espana', mode: 'season-dir', level: 1 },
  { association: 'ITA', country: 'Italy', competition: 'Serie A', repo: 'openfootball/italy', mode: 'season-dir', level: 1 },
  { association: 'ITA', country: 'Italy', competition: 'Serie B', repo: 'openfootball/italy', mode: 'season-dir', level: 2 },
  { association: 'FRA', country: 'France', competition: 'Ligue 1', repo: 'openfootball/europe', mode: 'flat-country', countryPath: 'france', level: 1 },
  { association: 'POR', country: 'Portugal', competition: 'Primeira Liga', repo: 'openfootball/europe', mode: 'flat-country', countryPath: 'portugal', level: 1 },
  { association: 'NED', country: 'Netherlands', competition: 'Eredivisie', repo: 'openfootball/europe', mode: 'flat-country', countryPath: 'netherlands', level: 1 },
  { association: 'TUR', country: 'Turkey', competition: 'Süper Lig', repo: 'openfootball/europe', mode: 'flat-country', countryPath: 'turkey', level: 1 },
  { association: 'CRO', country: 'Croatia', competition: 'HNL', repo: 'openfootball/europe', mode: 'flat-country', countryPath: 'croatia', level: 1 },
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
    candidates = files.filter((entry) => entry.name.startsWith(`${target.level}-`) && !entry.name.includes('-full') && !entry.name.includes('cup'));
  } else {
    const seasonPrefix = `${season}_`;
    const levelPattern = new RegExp(`${target.level}\\.txt$`, 'i');
    candidates = files.filter((entry) => entry.name.startsWith(seasonPrefix) && levelPattern.test(entry.name) && !entry.name.toLowerCase().includes('cup'));
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
  const re = new RegExp(`^#\\s*${label}s?\\s+(\\d+)\\s*$`, 'im');
  const match = text.match(re);
  return match ? Number(match[1]) : null;
}

function cleanTeam(value) {
  return value.replace(/\s+/g, ' ').trim();
}

function parseMatchLine(line) {
  // Variant used by some OpenFootball files: Team A v Team B 2-1 (1-0)
  let match = line.match(/^\s*(?:\d{1,2}:\d{2}\s+)?(.+?)\s+v\s+(.+?)\s+(\d+)-(\d+)(?:\s+\([^)]*\))?\s*$/i);
  if (match) {
    return { home: cleanTeam(match[1]), away: cleanTeam(match[2]), homeGoals: Number(match[3]), awayGoals: Number(match[4]) };
  }

  // Main current format: Team A 2-1 (1-0) Team B
  match = line.match(/^\s*(?:\d{1,2}:\d{2}\s+)?(.+?)\s+(\d+)-(\d+)(?:\s+\([^)]*\))?\s+(.+?)\s*$/);
  if (match) {
    return { home: cleanTeam(match[1]), away: cleanTeam(match[4]), homeGoals: Number(match[2]), awayGoals: Number(match[3]) };
  }
  return null;
}

function parseMatches(text) {
  const matches = [];
  for (const line of text.split(/\r?\n/)) {
    const parsed = parseMatchLine(line);
    if (!parsed) continue;
    if (!parsed.home || !parsed.away || parsed.home === parsed.away) continue;
    matches.push(parsed);
  }
  return matches;
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
  }));

  rows.sort((a, b) =>
    b.points - a.points ||
    b.goal_difference - a.goal_difference ||
    b.goals_for - a.goals_for ||
    a.team.localeCompare(b.team, 'en')
  );

  const n = rows.length;
  rows.forEach((row, index) => {
    row.sporting_rank = index + 1;
    row.finishing_percentile = n <= 1 ? null : (n - row.sporting_rank) / (n - 1);
    row.rank_fallback_used = index > 0 &&
      row.points === rows[index - 1].points &&
      row.goal_difference === rows[index - 1].goal_difference &&
      row.goals_for === rows[index - 1].goals_for;
  });
  return rows;
}

function auditGroup({ target, season, headerTeams, headerMatches, matches, table, source }) {
  const totalGf = table.reduce((sum, row) => sum + row.goals_for, 0);
  const totalGa = table.reduce((sum, row) => sum + row.goals_against, 0);
  const games = table.map((row) => row.played);
  const failures = [];
  if (headerTeams === null) failures.push('missing_header_teams');
  if (headerMatches === null) failures.push('missing_header_matches');
  if (headerTeams !== null && table.length !== headerTeams) failures.push('team_count_mismatch');
  if (headerMatches !== null && matches.length !== headerMatches) failures.push('match_count_mismatch');
  if (games.length && Math.min(...games) !== Math.max(...games)) failures.push('unequal_games_played');
  if (totalGf !== totalGa) failures.push('goals_balance_mismatch');
  if (table.some((row) => row.played !== row.wins + row.draws + row.losses)) failures.push('wdl_algebra_mismatch');
  if (table.some((row) => row.points !== row.wins * 3 + row.draws)) failures.push('points_algebra_mismatch');
  if (table.some((row) => !Number.isFinite(row.points_per_game) || !Number.isFinite(row.goal_difference_per_game))) failures.push('nonfinite_rate');

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
    parsed_matches: matches.length,
    min_matches_per_team: games.length ? Math.min(...games) : null,
    max_matches_per_team: games.length ? Math.max(...games) : null,
    rank_fallback_ties: table.filter((row) => row.rank_fallback_used).length,
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
    'season','association_code','country','competition','competition_level','team','sporting_rank','league_size',
    'finishing_percentile','played','wins','draws','losses','goals_for','goals_against','goal_difference','points',
    'points_per_game','goal_difference_per_game','rank_fallback_used','table_basis','source','source_ref','source_path',
    'source_git_blob_sha','source_file_sha256'
  ];
  return [cols.join(','), ...rows.map((row) => cols.map((col) => csvEscape(row[col])).join(','))].join('\n') + '\n';
}

async function main() {
  const allRows = [];
  const groups = [];
  const sourceFiles = [];

  for (const target of TARGETS) {
    for (const season of SEASONS) {
      process.stderr.write(`Acquire ${target.association} ${target.competition} ${season}...\n`);
      try {
        const source = await discoverSource(target, season);
        const text = await fetchText(source.download_url);
        const fileSha256 = sha256(text);
        const headerTeams = parseHeaderNumber(text, 'Team');
        const headerMatches = parseHeaderNumber(text, 'Match');
        const matches = parseMatches(text);
        const table = buildTable(matches);
        const groupAudit = auditGroup({ target, season, headerTeams, headerMatches, matches, table, source });
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
            sporting_rank: row.sporting_rank,
            league_size: table.length,
            finishing_percentile: row.finishing_percentile,
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
            rank_fallback_used: row.rank_fallback_used,
            table_basis: 'match_results_3_1_0__rank_points_gd_gf',
            source: source.repository,
            source_ref: source.source_ref,
            source_path: source.source_path,
            source_git_blob_sha: source.git_blob_sha,
            source_file_sha256: fileSha256,
          });
        }
        process.stderr.write(`  ${groupAudit.status}: ${matches.length} matches, ${table.length} teams\n`);
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
    dataset: 'FantaNexus Domestic Strength Raw v0',
    status: failedGroups.length || duplicateKeys.length ? 'FAIL' : 'PASS',
    generated_at: new Date().toISOString(),
    policy: {
      seasons: SEASONS,
      scope: 'straight-table winter domestic leagues; Italy includes Serie B',
      metrics: ['points_per_game', 'goal_difference_per_game', 'finishing_percentile'],
      finishing_percentile_formula: '(league_size - sporting_rank) / (league_size - 1)',
      ranking_basis: 'match-derived points, goal difference, goals for; club name only as deterministic final fallback',
      excluded_from_v0: 'split/halved-points competitions and summer-calendar leagues pending rules-aware adapters',
    },
    rows: allRows.length,
    groups_expected: TARGETS.length * SEASONS.length,
    groups_pass: groups.length - failedGroups.length,
    groups_fail: failedGroups.length,
    duplicate_team_season_keys: duplicateKeys.length,
    duplicate_examples: duplicateKeys.slice(0, 25),
    groups,
  };

  await fs.mkdir(OUT_DIR, { recursive: true });
  const jsonPath = path.join(OUT_DIR, 'fantanexus_domestic_strength_raw_2021_2026_v0.json');
  const csvPath = path.join(OUT_DIR, 'fantanexus_domestic_strength_raw_2021_2026_v0.csv');
  const auditPath = path.join(OUT_DIR, 'fantanexus_domestic_strength_raw_2021_2026_v0_audit.json');
  const manifestPath = path.join(OUT_DIR, 'fantanexus_domestic_strength_raw_2021_2026_v0_manifest.json');

  const jsonText = JSON.stringify(allRows, null, 2) + '\n';
  const csvText = toCsv(allRows);
  const auditText = JSON.stringify(audit, null, 2) + '\n';
  const manifest = {
    dataset: 'fantanexus_domestic_strength_raw_2021_2026_v0',
    status: audit.status,
    generated_at: new Date().toISOString(),
    seasons: SEASONS,
    associations: [...new Set(TARGETS.map((target) => target.association))],
    competitions: TARGETS.map((target) => `${target.association}:${target.competition}`),
    rows: allRows.length,
    source_files: sourceFiles,
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
