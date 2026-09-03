#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'

const ROOT = '.nexus-f1-lega-snapshot-v1'
const RAW = path.join(ROOT, 'raw')
const CONFIG_PATH = 'config/nexus-f1-lega-snapshot-v1.json'
const CONFIG = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'))

function fail(message) { throw new Error(`Nexus F1 Lega snapshot: ${message}`) }
function sha256Buffer(value) { return crypto.createHash('sha256').update(value).digest('hex') }
function sha256File(file) { return sha256Buffer(fs.readFileSync(file)) }
function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)) }
function safe(value) { return String(value).replace(/[^A-Za-z0-9._-]+/gu, '_') }
function enc(value) { return encodeURIComponent(value) }
function ensureDir(dir) { fs.mkdirSync(dir, { recursive: true }) }
function writeRaw(file, text) { ensureDir(path.dirname(file)); fs.writeFileSync(file, text) }
function writeJson(file, value) { ensureDir(path.dirname(file)); fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n') }

if (CONFIG.schema !== 'NEXUS_F1_LEGA_SNAPSHOT_CONFIG_V1' || CONFIG.protocolVersion !== '1.1') fail('config schema/protocol mismatch')
if (!Array.isArray(CONFIG.targetSeasons) || CONFIG.targetSeasons.length === 0) fail('targetSeasons missing')
if (CONFIG.oldArtifact?.freshSnapshotIsRecovery !== false) fail('fresh snapshot must not be labelled old-artifact recovery')
if (CONFIG.governance?.rawOnly !== true || CONFIG.governance?.normalizationAllowed !== false || CONFIG.governance?.stintDerivationAllowed !== false) fail('RAW governance mismatch')

fs.rmSync(ROOT, { recursive: true, force: true })
ensureDir(RAW)

const requestLog = []
let lastRequestAt = 0
let callCount = 0

async function getRaw(url, logicalId) {
  const delay = Math.max(0, Number(CONFIG.requestDelayMs) - (Date.now() - lastRequestAt))
  if (delay > 0) await sleep(delay)

  let lastError
  for (let attempt = 1; attempt <= Number(CONFIG.maxRetries) + 1; attempt++) {
    const requestedAt = new Date().toISOString()
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), Number(CONFIG.requestTimeoutMs))
    try {
      lastRequestAt = Date.now()
      const response = await fetch(url, {
        headers: {
          accept: 'application/json',
          'user-agent': CONFIG.userAgent,
        },
        signal: controller.signal,
      })
      const text = await response.text()
      const receivedAt = new Date().toISOString()
      clearTimeout(timer)
      callCount += 1
      const headers = {
        date: response.headers.get('date'),
        etag: response.headers.get('etag'),
        lastModified: response.headers.get('last-modified'),
        contentType: response.headers.get('content-type'),
      }
      if (!response.ok) {
        lastError = new Error(`HTTP ${response.status} ${logicalId}`)
        requestLog.push({ logicalId, url, attempt, requestedAt, receivedAt, status: response.status, ok: false, headers, bytes: Buffer.byteLength(text), sha256: sha256Buffer(text) })
      } else {
        let json
        try { json = JSON.parse(text) } catch { throw new Error(`non-JSON response ${logicalId}`) }
        requestLog.push({ logicalId, url, attempt, requestedAt, receivedAt, status: response.status, ok: true, headers, bytes: Buffer.byteLength(text), sha256: sha256Buffer(text) })
        return { text, json, requestedAt, receivedAt, status: response.status, headers, sha256: sha256Buffer(text), bytes: Buffer.byteLength(text) }
      }
    } catch (error) {
      clearTimeout(timer)
      lastError = error
    }
    if (attempt <= Number(CONFIG.maxRetries)) await sleep(750 * attempt)
  }
  throw lastError ?? new Error(`request failed ${logicalId}`)
}

function seasonName(row) { return row?.seasonName ?? row?.name ?? null }
function seasonId(row) { return row?.seasonId ?? row?.id ?? null }
function matchId(row) { return row?.matchId ?? row?.id ?? null }
function hasJsonContent(value) {
  if (Array.isArray(value)) return value.length > 0
  return value && typeof value === 'object' && Object.keys(value).length > 0
}

const startedAt = new Date().toISOString()
const base = CONFIG.baseUrl.replace(/\/$/u, '')
const competition = enc(CONFIG.competitionId)
const locale = encodeURIComponent(CONFIG.locale)

const catalogUrl = `${base}/competitions/${competition}/seasons?locale=${locale}`
const catalog = await getRaw(catalogUrl, 'season-catalog')
const catalogPath = path.join(RAW, 'season-catalog.json')
writeRaw(catalogPath, catalog.text)

const catalogRows = catalog.json?.seasons
if (!Array.isArray(catalogRows) || catalogRows.length === 0) fail('season catalog missing seasons[]')
const selected = CONFIG.targetSeasons.map(name => {
  const row = catalogRows.find(candidate => seasonName(candidate) === name)
  if (!row) fail(`season not found in catalog: ${name}`)
  const id = seasonId(row)
  if (!id) fail(`seasonId missing for ${name}`)
  return { name, id }
})
if (new Set(selected.map(s => s.id)).size !== selected.length) fail('duplicate selected seasonId')

const manifestFiles = [{ path: catalogPath, logicalId: 'season-catalog', sha256: catalog.sha256, bytes: catalog.bytes, capturedAt: catalog.receivedAt, availableAt: null, responseHeaders: catalog.headers }]
const seasons = []

for (const season of selected) {
  const seasonDir = path.join(RAW, safe(season.name))
  const matchesUrl = `${base}/seasons/${enc(season.id)}/matches?locale=${locale}`
  const matchesResponse = await getRaw(matchesUrl, `matches:${season.name}`)
  const matchesPath = path.join(seasonDir, 'matches.json')
  writeRaw(matchesPath, matchesResponse.text)
  manifestFiles.push({ path: matchesPath, logicalId: `matches:${season.name}`, sha256: matchesResponse.sha256, bytes: matchesResponse.bytes, capturedAt: matchesResponse.receivedAt, availableAt: null, responseHeaders: matchesResponse.headers })

  const matches = matchesResponse.json?.matches
  if (!Array.isArray(matches)) fail(`matches[] missing for ${season.name}`)
  if (matches.length !== Number(CONFIG.expectedRegularSeasonMatchesPerSeason)) fail(`expected ${CONFIG.expectedRegularSeasonMatchesPerSeason} matches for ${season.name}, got ${matches.length}`)
  const ids = matches.map(matchId)
  if (ids.some(id => !id)) fail(`matchId missing in ${season.name}`)
  if (new Set(ids).size !== ids.length) fail(`duplicate matchId in ${season.name}`)

  const lineupRecords = []
  for (let index = 0; index < matches.length; index++) {
    const match = matches[index]
    const id = matchId(match)
    const lineupUrl = `${base}/match/${enc(id)}/lineups?locale=${locale}`
    const lineup = await getRaw(lineupUrl, `lineup:${season.name}:${id}`)
    if (!hasJsonContent(lineup.json)) fail(`empty lineup payload ${season.name} ${id}`)
    const fileName = `${String(index + 1).padStart(3, '0')}-${safe(id)}.json`
    const file = path.join(seasonDir, 'lineups', fileName)
    writeRaw(file, lineup.text)
    const rec = {
      matchId: id,
      matchDateUtc: match?.matchDateUtc ?? null,
      matchStatus: match?.status ?? null,
      homeTeamId: match?.home?.teamId ?? null,
      awayTeamId: match?.away?.teamId ?? null,
      file,
      sha256: lineup.sha256,
      bytes: lineup.bytes,
      capturedAt: lineup.receivedAt,
      availableAt: null,
      responseHeaders: lineup.headers,
    }
    lineupRecords.push(rec)
    manifestFiles.push({ path: file, logicalId: `lineup:${season.name}:${id}`, sha256: lineup.sha256, bytes: lineup.bytes, capturedAt: lineup.receivedAt, availableAt: null, responseHeaders: lineup.headers })
  }

  seasons.push({
    seasonName: season.name,
    seasonId: season.id,
    matchCount: matches.length,
    uniqueMatchIds: new Set(ids).size,
    lineupPayloadCount: lineupRecords.length,
    matchesFile: matchesPath,
    matchesSha256: matchesResponse.sha256,
    lineups: lineupRecords,
  })
  console.log(`${season.name}: ${matches.length} matches, ${lineupRecords.length} raw lineup payloads`)
}

const completedAt = new Date().toISOString()
const orderedContentIndex = manifestFiles
  .map(row => `${row.path}|${row.sha256}|${row.bytes}`)
  .sort()
  .join('\n')
const snapshotContentSha256 = sha256Buffer(orderedContentIndex)
const configSha256 = sha256File(CONFIG_PATH)
const responseLogPath = path.join(ROOT, 'response-log.json')
writeJson(responseLogPath, requestLog)

const manifest = {
  schema: 'NEXUS_F1_LEGA_RAW_SNAPSHOT_MANIFEST_V1',
  protocolVersion: '1.1',
  status: 'FRESH_RAW_SNAPSHOT_CAPTURED_NOT_F1_PROMOTED',
  purpose: CONFIG.purpose,
  source: {
    provider: 'Lega Serie A',
    surface: 'Sports Data Platform',
    baseUrl: CONFIG.baseUrl,
    competitionId: CONFIG.competitionId,
  },
  freshAcquisition: true,
  oldArtifactReference: CONFIG.oldArtifact,
  startedAt,
  completedAt,
  codeCommit: process.env.GITHUB_SHA ?? 'LOCAL_UNKNOWN',
  githubRunId: process.env.GITHUB_RUN_ID ? Number(process.env.GITHUB_RUN_ID) : null,
  githubRunAttempt: process.env.GITHUB_RUN_ATTEMPT ? Number(process.env.GITHUB_RUN_ATTEMPT) : null,
  runtime: process.version,
  randomSeed: 'NOT_APPLICABLE_DETERMINISTIC_ACQUISITION',
  configurationPath: CONFIG_PATH,
  configurationSha256: configSha256,
  temporalPolicy: CONFIG.temporalPolicy,
  availableAtPolicy: 'UNASSIGNED_IN_RAW_SNAPSHOT; provider event timestamps and HTTP response metadata preserved separately',
  catalog: { file: catalogPath, sha256: catalog.sha256, bytes: catalog.bytes, seasonCatalogRows: catalogRows.length },
  seasons,
  totals: {
    seasons: seasons.length,
    matches: seasons.reduce((sum, s) => sum + s.matchCount, 0),
    lineupPayloads: seasons.reduce((sum, s) => sum + s.lineupPayloadCount, 0),
    successfulHttpResponses: requestLog.filter(row => row.ok).length,
    failedAttempts: requestLog.filter(row => !row.ok).length,
    callsIncludingFailedAttempts: callCount,
  },
  snapshotContentSha256,
  contentIndexDefinition: 'SHA256 over lexicographically sorted path|sha256|bytes for raw source files only',
  responseLog: { file: responseLogPath, sha256: sha256File(responseLogPath) },
  semanticLineupValidationPerformed: false,
  normalizationPerformed: false,
  stintDerivationPerformed: false,
  historicalReplayPromotion: false,
  f1Closed: false,
  f2PlusAuthorized: false,
  canonicalMutation: false,
}
const manifestPath = path.join(ROOT, 'manifest.json')
writeJson(manifestPath, manifest)
const manifestSha256 = sha256File(manifestPath)
writeJson(path.join(ROOT, 'audit.json'), {
  schema: 'NEXUS_F1_LEGA_RAW_SNAPSHOT_AUDIT_V1',
  protocolVersion: '1.1',
  status: 'PASS_RAW_ACQUISITION_ONLY',
  manifestSha256,
  snapshotContentSha256,
  expectedSeasons: CONFIG.targetSeasons.length,
  observedSeasons: seasons.length,
  expectedMatches: CONFIG.targetSeasons.length * Number(CONFIG.expectedRegularSeasonMatchesPerSeason),
  observedMatches: manifest.totals.matches,
  expectedLineupPayloads: CONFIG.targetSeasons.length * Number(CONFIG.expectedRegularSeasonMatchesPerSeason),
  observedLineupPayloads: manifest.totals.lineupPayloads,
  oldArtifactRecovered: false,
  availableAtAssigned: false,
  normalizationPerformed: false,
  stintDerivationPerformed: false,
  f1Closed: false,
  nextRequiredStep: 'SEMANTIC_LINEUP_AUDIT_AND_F1_RAW_STINT_DERIVATION_WITH_RECONCILIATION',
})

console.log(JSON.stringify({
  status: 'PASS_RAW_ACQUISITION_ONLY',
  seasons: seasons.length,
  matches: manifest.totals.matches,
  lineupPayloads: manifest.totals.lineupPayloads,
  manifestSha256,
  snapshotContentSha256,
  oldArtifactRecovered: false,
}, null, 2))
