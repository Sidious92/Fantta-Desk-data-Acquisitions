import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';

const YEARS = [2021, 2022, 2023, 2024, 2025, 2026];
const OUT_DIR = '.nexus-uefa-club-coefficients-v0/acquisition';
const SOURCE_URL = (year) => `https://kassiesa.net/uefa/data/method5/trank${year}.html`;
const TOP5_2026 = [
  ['Bayern München', 147.5],
  ['Real Madrid', 144.5],
  ['Paris Saint-Germain', 132.0],
  ['Liverpool', 130.0],
  ['Internazionale', 127.0],
];

const COUNTRY_CODES = Object.freeze({
  alb:'ALB', and:'AND', arm:'ARM', aut:'AUT', azb:'AZE', aze:'AZE', bel:'BEL', bls:'BLR', blr:'BLR',
  bos:'BIH', bih:'BIH', bul:'BUL', cro:'CRO', cyp:'CYP', cze:'CZE', den:'DEN', eng:'ENG', esp:'ESP',
  est:'EST', far:'FRO', fro:'FRO', fin:'FIN', fra:'FRA', geo:'GEO', ger:'GER', gib:'GIB', gre:'GRE',
  hun:'HUN', isl:'ISL', irl:'IRL', isr:'ISR', ita:'ITA', kaz:'KAZ', kos:'KOS', lat:'LVA', lva:'LVA',
  lie:'LIE', lit:'LTU', ltu:'LTU', lux:'LUX', mac:'MKD', mkd:'MKD', mlt:'MLT', mol:'MDA', mda:'MDA',
  mon:'MNE', mne:'MNE', ned:'NED', nir:'NIR', nor:'NOR', pol:'POL', por:'POR', rom:'ROU', rou:'ROU',
  rus:'RUS', sco:'SCO', sma:'SMR', smr:'SMR', slo:'SVN', svn:'SVN', srb:'SRB', sui:'SUI', svk:'SVK',
  swe:'SWE', tur:'TUR', ukr:'UKR', wal:'WAL',
});

const PRESEASON_FOR = Object.freeze({
  2021:'2021/22', 2022:'2022/23', 2023:'2023/24', 2024:'2024/25', 2025:'2025/26', 2026:'2026/27',
});

function decodeHtml(s) {
  return s
    .replace(/&nbsp;|&#160;/gi, ' ')
    .replace(/&amp;/gi, '&')
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)));
}

function textOf(html) {
  return decodeHtml(html.replace(/<br\s*\/?\s*>/gi, ' ').replace(/<[^>]+>/g, '')).replace(/\s+/g, ' ').trim();
}

function parseNumber(value) {
  const s = String(value ?? '').trim().replace(/,/g, '');
  if (!s || !/^-?\d+(?:\.\d+)?$/.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

function normalizeClubName(name) {
  return name.normalize('NFKC').replace(/\s+/g, ' ').trim();
}

function clubKey(name) {
  return normalizeClubName(name).toLocaleLowerCase('en-US');
}

function rowsFromHtml(html) {
  const rows = [];
  const re = /<tr\b[^>]*>([\s\S]*?)<\/tr>/gi;
  for (const m of html.matchAll(re)) {
    const cells = [];
    const cellRe = /<t[dh]\b[^>]*>([\s\S]*?)<\/t[dh]>/gi;
    for (const c of m[1].matchAll(cellRe)) cells.push(textOf(c[1]));
    if (cells.length) rows.push(cells);
  }
  return rows;
}

function parseSnapshotHtml(html, year) {
  const parsed = [];
  for (const cells of rowsFromHtml(html)) {
    let countryIndex = -1;
    let associationCode = null;
    for (let i = 0; i < cells.length; i += 1) {
      const key = cells[i].trim().toLowerCase();
      if (COUNTRY_CODES[key]) {
        countryIndex = i;
        associationCode = COUNTRY_CODES[key];
        break;
      }
    }
    if (countryIndex < 1) continue;

    const clubName = normalizeClubName(cells[countryIndex - 1]);
    if (!clubName) continue;

    const tail = cells.slice(countryIndex + 1);
    if (tail.length < 7) continue;
    const structuredTail = tail.slice(-7);
    const componentCells = structuredTail.slice(0, 5);
    const clubPoints5y = parseNumber(structuredTail[5]);
    const associationFloor20pct = parseNumber(structuredTail[6]);
    if (clubPoints5y === null || associationFloor20pct === null) continue;

    const components = componentCells.map(parseNumber);
    const coefficient5y = Math.max(clubPoints5y, associationFloor20pct);
    parsed.push({
      snapshot_year: year,
      preseason_for: PRESEASON_FOR[year],
      source_rank_raw: parseNumber(cells[0]),
      club: clubName,
      club_key: clubKey(clubName),
      association_code: associationCode,
      window_s1: components[0],
      window_s2: components[1],
      window_s3: components[2],
      window_s4: components[3],
      window_s5: components[4],
      club_points_5y: clubPoints5y,
      association_floor_20pct: associationFloor20pct,
      coefficient_5y: coefficient5y,
      uses_association_floor: associationFloor20pct > clubPoints5y + 1e-9,
      source: 'Kassiesa / public UEFA coefficient tables',
      source_ref: SOURCE_URL(year),
    });
  }

  parsed.sort((a, b) =>
    b.coefficient_5y - a.coefficient_5y ||
    b.club_points_5y - a.club_points_5y ||
    a.club.localeCompare(b.club, 'en')
  );
  let rank = 0;
  let last = null;
  parsed.forEach((row, i) => {
    if (last === null || Math.abs(row.coefficient_5y - last) > 1e-9) rank = i + 1;
    row.rank = rank;
    last = row.coefficient_5y;
  });
  return parsed;
}

async function fetchText(url) {
  let lastError;
  for (let attempt = 1; attempt <= 4; attempt += 1) {
    try {
      const res = await fetch(url, { headers: { 'user-agent': 'FantaNexus/0.1 UEFA coefficient acquisition' } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.text();
    } catch (err) {
      lastError = err;
      if (attempt < 4) await new Promise((r) => setTimeout(r, 750 * attempt));
    }
  }
  throw new Error(`Failed to fetch ${url}: ${lastError?.message ?? lastError}`);
}

function componentSum(row) {
  return ['window_s1','window_s2','window_s3','window_s4','window_s5']
    .reduce((sum, key) => sum + (row[key] ?? 0), 0);
}

function componentTolerance(row) {
  const n = ['window_s1','window_s2','window_s3','window_s4','window_s5']
    .filter((key) => row[key] !== null).length;
  return 0.0051 * n + 1e-9;
}

function auditRows(rows) {
  const byYear = Object.fromEntries(YEARS.map((year) => [year, rows.filter((r) => r.snapshot_year === year)]));
  const checks = [];
  const failures = [];
  const add = (name, pass, details) => {
    checks.push({ name, pass, details });
    if (!pass) failures.push(name);
  };

  for (const year of YEARS) {
    const ys = byYear[year];
    add(`rows_${year}_gte_150`, ys.length >= 150, { rows: ys.length });

    const seen = new Set();
    const dupes = [];
    for (const row of ys) {
      const key = `${row.association_code}|${row.club_key}`;
      if (seen.has(key)) dupes.push(key); else seen.add(key);
    }
    add(`duplicates_${year}_zero`, dupes.length === 0, { duplicates: dupes.slice(0, 25), count: dupes.length });

    const badFormula = ys.filter((r) => Math.abs(r.coefficient_5y - Math.max(r.club_points_5y, r.association_floor_20pct)) > 1e-9);
    add(`coefficient_formula_${year}`, badFormula.length === 0, { count: badFormula.length });

    const badFloorFlag = ys.filter((r) => r.uses_association_floor !== (r.association_floor_20pct > r.club_points_5y + 1e-9));
    add(`floor_flag_${year}`, badFloorFlag.length === 0, { count: badFloorFlag.length });

    const componentMismatches = ys.filter((r) => Math.abs(componentSum(r) - r.club_points_5y) > componentTolerance(r));
    add(`component_sum_${year}`, componentMismatches.length === 0, {
      count: componentMismatches.length,
      examples: componentMismatches.slice(0, 10).map((r) => ({ club:r.club, sum:componentSum(r), total:r.club_points_5y, tolerance:componentTolerance(r) })),
    });

    const orderingBad = ys.some((r, i) => i > 0 && r.coefficient_5y > ys[i - 1].coefficient_5y + 1e-9);
    add(`ordering_${year}`, !orderingBad, { rows: ys.length });
  }

  const top5 = byYear[2026].slice(0, 5);
  const top5Pass = TOP5_2026.every(([name, coeff], i) => {
    const row = top5[i];
    return row && row.club === name && Math.abs(row.coefficient_5y - coeff) < 1e-9;
  });
  add('top5_2026_official_crosscheck', top5Pass, { expected: TOP5_2026, actual: top5.map((r) => [r.club, r.coefficient_5y]) });

  return {
    status: failures.length ? 'FAIL' : 'PASS',
    generated_at: new Date().toISOString(),
    snapshots: Object.fromEntries(YEARS.map((year) => [year, {
      rows: byYear[year].length,
      floor_used: byYear[year].filter((r) => r.uses_association_floor).length,
      associations: new Set(byYear[year].map((r) => r.association_code)).size,
    }])),
    checks,
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
    'snapshot_year','preseason_for','rank','source_rank_raw','club','club_key','association_code',
    'window_s1','window_s2','window_s3','window_s4','window_s5','club_points_5y',
    'association_floor_20pct','coefficient_5y','uses_association_floor','source','source_ref',
  ];
  return [cols.join(','), ...rows.map((row) => cols.map((c) => csvEscape(row[c])).join(','))].join('\n') + '\n';
}

function sha256(text) {
  return crypto.createHash('sha256').update(text).digest('hex');
}

async function main() {
  const snapshots = [];
  for (const year of YEARS) {
    const html = await fetchText(SOURCE_URL(year));
    const rows = parseSnapshotHtml(html, year);
    snapshots.push(...rows);
    process.stderr.write(`UEFA club coefficient ${year}: ${rows.length} rows\n`);
  }

  const audit = auditRows(snapshots);
  await fs.mkdir(OUT_DIR, { recursive: true });

  const jsonPath = path.join(OUT_DIR, 'fantanexus_uefa_club_coefficients_2021_2026_v0.json');
  const csvPath = path.join(OUT_DIR, 'fantanexus_uefa_club_coefficients_2021_2026_v0.csv');
  const auditPath = path.join(OUT_DIR, 'fantanexus_uefa_club_coefficients_2021_2026_v0_audit.json');
  const manifestPath = path.join(OUT_DIR, 'fantanexus_uefa_club_coefficients_2021_2026_v0_manifest.json');

  const jsonText = JSON.stringify(snapshots, null, 2) + '\n';
  const csvText = toCsv(snapshots);
  const auditText = JSON.stringify(audit, null, 2) + '\n';
  const manifest = {
    dataset: 'fantanexus_uefa_club_coefficients_2021_2026_v0',
    status: audit.status,
    generated_at: new Date().toISOString(),
    snapshot_years: YEARS,
    rows: snapshots.length,
    sources: YEARS.map((year) => SOURCE_URL(year)),
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

  process.stderr.write(`Audit: ${audit.status}\n`);
  if (audit.status !== 'PASS') process.exitCode = 1;
}

await main();
