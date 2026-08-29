#!/usr/bin/env node

import { createHash } from 'node:crypto'
import { mkdir, rm, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

export const ENDPOINT = 'https://dapi.legaseriea.it/v2/content/it-IT/playertransfers'
export const PAGE_LIMIT = 10
export const SORT_FIELD = 'fields.transferDate'
export const INITIAL_URL = `${ENDPOINT}?$limit=${PAGE_LIMIT}&$sort=${SORT_FIELD}&$skip=0`
export const MAX_PASSES = 4
export const MAX_PAGES = 1000

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]),
    )
  }
  return value
}

export function canonicalJson(value) {
  return `${JSON.stringify(canonicalize(value))}\n`
}

export function sha256(value) {
  return createHash('sha256').update(value).digest('hex')
}

function sourceString(value) {
  const normalized = String(value ?? '').trim()
  return normalized || null
}

function sourceFieldStatus(value) {
  return sourceString(value) ? 'PRESENT' : 'SOURCE_MISSING'
}

export function normalizeTransferType(value) {
  const normalized = String(value ?? '').trim().toLocaleLowerCase('it-IT')
  if (normalized === 'definitivo') return 'PERMANENT'
  if (normalized === 'temporaneo') return 'LOAN'
  if (normalized) return 'OTHER_EXPLICIT'
  return 'UNRESOLVED'
}

export function validateEnumerationUrl(rawUrl, { previousSkip = -1 } = {}) {
  const url = new URL(rawUrl)
  if (url.protocol !== 'https:') throw new Error(`Transfer acquisition: protocollo non ammesso ${url.protocol}`)
  if (url.hostname !== 'dapi.legaseriea.it') throw new Error(`Transfer acquisition: host non ammesso ${url.hostname}`)
  if (url.pathname !== '/v2/content/it-IT/playertransfers') {
    throw new Error(`Transfer acquisition: path non ammesso ${url.pathname}`)
  }

  const limit = Number(url.searchParams.get('$limit'))
  const skip = Number(url.searchParams.get('$skip'))
  const sort = url.searchParams.get('$sort')

  if (limit !== PAGE_LIMIT) throw new Error(`Transfer acquisition: $limit inatteso ${limit}`)
  if (!Number.isInteger(skip) || skip < 0) throw new Error(`Transfer acquisition: $skip non valido ${skip}`)
  if (skip <= previousSkip) throw new Error(`Transfer acquisition: $skip non crescente ${skip} <= ${previousSkip}`)
  if (sort !== SORT_FIELD) throw new Error(`Transfer acquisition: $sort inatteso ${sort}`)

  return { url, skip }
}

function validateItem(item) {
  if (!item || typeof item !== 'object') throw new Error('Transfer acquisition: item non-oggetto')
  if (!String(item._entityId ?? '').trim()) throw new Error('Transfer acquisition: _entityId mancante')
  if (item.entityCode !== 'playertransfer') {
    throw new Error(`Transfer acquisition: entityCode inatteso ${item.entityCode}`)
  }
  if (!item.fields || typeof item.fields !== 'object') throw new Error(`Transfer acquisition: fields mancanti per ${item._entityId}`)
  if (!sourceString(item.fields.clubTo)) throw new Error(`Transfer acquisition: clubTo mancante per ${item._entityId}`)

  const sourceName = sourceString(item.title)
    || [item.fields.playerName, item.fields.playerSurname].map(sourceString).filter(Boolean).join(' ')
  if (!sourceName) throw new Error(`Transfer acquisition: nome giocatore mancante per ${item._entityId}`)
}

export function materializeEvent(item, observedAt) {
  validateItem(item)
  const sourceRecordCanonical = canonicalJson(item)
  const sourceRecordSha256 = sha256(sourceRecordCanonical)
  const originClubSource = sourceString(item.fields.clubFrom)
  const destinationClubSource = sourceString(item.fields.clubTo)
  const transferTypeSource = sourceString(item.fields.transferType)
  const transferDateSource = sourceString(item.fields.transferDate)
  const playerNameSource = sourceString(item.title)
    || [item.fields.playerName, item.fields.playerSurname].map(sourceString).filter(Boolean).join(' ')

  return {
    eventId: `LEGA_SERIE_A_DAPI:${String(item._entityId).trim()}`,
    nexusPlayerId: null,
    playerNameSource,
    originClubSource,
    destinationClubSource,
    originLeague: null,
    destinationLeague: null,
    transferTypeSource,
    transferTypeNormalized: normalizeTransferType(transferTypeSource),
    effectiveAt: null,
    publishedAt: null,
    knownAt: null,
    observedAt,
    sourceTemporalFields: {
      transferDate: transferDateSource,
      contentDate: sourceString(item.contentDate),
      lastUpdatedDate: sourceString(item.lastUpdatedDate),
    },
    sourceFieldStatus: {
      originClub: sourceFieldStatus(item.fields.clubFrom),
      destinationClub: sourceFieldStatus(item.fields.clubTo),
      transferType: sourceFieldStatus(item.fields.transferType),
      transferDate: sourceFieldStatus(item.fields.transferDate),
    },
    sourceProvider: 'LEGA_SERIE_A_OFFICIAL_DAPI',
    sourceUrl: String(item.selfUrl ?? ENDPOINT),
    sourceRecordRaw: item,
    sourceRecordSha256,
    identityStatus: 'UNRESOLVED',
  }
}

async function fetchJson(url, fetchFn) {
  const response = await fetchFn(url, {
    method: 'GET',
    headers: {
      accept: 'application/json',
    },
    redirect: 'error',
  })
  if (!response.ok) throw new Error(`Transfer acquisition: HTTP ${response.status} per ${url}`)
  const contentType = response.headers?.get?.('content-type') ?? ''
  if (contentType && !contentType.toLowerCase().includes('application/json')) {
    throw new Error(`Transfer acquisition: content-type inatteso ${contentType}`)
  }
  return response.json()
}

export async function enumerateOnce({ fetchFn = fetch, observedAt = new Date().toISOString() } = {}) {
  let nextUrl = INITIAL_URL
  let previousSkip = -1
  const pages = []
  const items = []
  const seen = new Set()
  const duplicateEntityIds = new Set()

  while (nextUrl) {
    if (pages.length >= MAX_PAGES) throw new Error(`Transfer acquisition: superato MAX_PAGES=${MAX_PAGES}`)
    const { skip } = validateEnumerationUrl(nextUrl, { previousSkip })
    previousSkip = skip

    const payload = await fetchJson(nextUrl, fetchFn)
    if (!payload || typeof payload !== 'object') throw new Error('Transfer acquisition: payload non-oggetto')
    if (!Array.isArray(payload.items)) throw new Error('Transfer acquisition: items[] mancante')
    if (!payload.pagination || typeof payload.pagination !== 'object') {
      throw new Error('Transfer acquisition: pagination mancante')
    }

    const pageCanonical = canonicalJson(payload)
    pages.push({
      index: pages.length,
      requestUrl: nextUrl,
      skip,
      itemCount: payload.items.length,
      sha256: sha256(pageCanonical),
      generatedAt: payload.meta?.generatedAt ?? null,
      payload,
    })

    for (const item of payload.items) {
      validateItem(item)
      const id = String(item._entityId).trim()
      if (seen.has(id)) duplicateEntityIds.add(id)
      seen.add(id)
      items.push(item)
    }

    const candidateNext = payload.pagination.nextUrl
    if (payload.items.length === 0) {
      if (candidateNext) throw new Error('Transfer acquisition: pagina vuota con nextUrl presente')
      nextUrl = null
      break
    }

    if (!candidateNext) {
      nextUrl = null
      break
    }

    validateEnumerationUrl(candidateNext, { previousSkip })
    nextUrl = candidateNext
  }

  const uniqueById = new Map()
  for (const item of items) uniqueById.set(String(item._entityId).trim(), item)
  const sortedUniqueItems = [...uniqueById.values()].sort((a, b) => String(a._entityId).localeCompare(String(b._entityId)))
  const recordDigests = sortedUniqueItems.map((item) => [String(item._entityId).trim(), sha256(canonicalJson(item))])
  const snapshotSha256 = sha256(canonicalJson(recordDigests))

  return {
    observedAt,
    pages,
    rawItemCount: items.length,
    uniqueItemCount: sortedUniqueItems.length,
    duplicateEntityIds: [...duplicateEntityIds].sort(),
    sortedUniqueItems,
    snapshotSha256,
  }
}

export function isStablePair(left, right) {
  return left.duplicateEntityIds.length === 0
    && right.duplicateEntityIds.length === 0
    && left.uniqueItemCount === right.uniqueItemCount
    && left.snapshotSha256 === right.snapshotSha256
}

export async function acquireStableSnapshot({ fetchFn = fetch, maxPasses = MAX_PASSES } = {}) {
  if (!Number.isInteger(maxPasses) || maxPasses < 2) throw new Error('Transfer acquisition: maxPasses deve essere >= 2')
  const passes = []

  for (let index = 0; index < maxPasses; index += 1) {
    const pass = await enumerateOnce({ fetchFn, observedAt: new Date().toISOString() })
    passes.push(pass)
    if (passes.length >= 2 && isStablePair(passes.at(-2), passes.at(-1))) {
      return {
        status: 'STABLE_FULL_ENUMERATION',
        passes,
        finalPass: passes.at(-1),
        stablePair: [passes.length - 2, passes.length - 1],
      }
    }
  }

  throw new Error(`Transfer acquisition: nessuna coppia di enumerazioni consecutive stabile in ${maxPasses} pass`)
}

async function persistAcquisition(acquisition, outputRoot) {
  const finalPass = acquisition.finalPass
  await rm(outputRoot, { recursive: true, force: true })
  await mkdir(resolve(outputRoot, 'raw'), { recursive: true })

  const pageReceipts = []
  for (const page of finalPass.pages) {
    const name = `page-${String(page.index).padStart(4, '0')}.json`
    const content = canonicalJson(page.payload)
    await writeFile(resolve(outputRoot, 'raw', name), content, 'utf8')
    pageReceipts.push({
      path: `raw/${name}`,
      requestUrl: page.requestUrl,
      skip: page.skip,
      itemCount: page.itemCount,
      generatedAt: page.generatedAt,
      sha256: sha256(content),
    })
  }

  const events = finalPass.sortedUniqueItems
    .map((item) => materializeEvent(item, finalPass.observedAt))
    .sort((a, b) => a.eventId.localeCompare(b.eventId))
  const eventsDocument = {
    schema: 'NEXUS_TRANSFER_EVENT_CURRENT_LEDGER_V1',
    status: 'SOURCE_ENUMERATED_IDENTITY_JOIN_PENDING',
    targetSeason: '2026/27',
    observedAt: finalPass.observedAt,
    sourceProvider: 'LEGA_SERIE_A_OFFICIAL_DAPI',
    sourceEndpoint: ENDPOINT,
    events,
  }
  const eventsContent = canonicalJson(eventsDocument)
  await writeFile(resolve(outputRoot, 'transfer-events-current-v1.json'), eventsContent, 'utf8')

  const manifest = {
    schema: 'NEXUS_TRANSFER_EVENT_CURRENT_ACQUISITION_MANIFEST_V1',
    status: 'PASS_STABLE_FULL_ENUMERATION',
    targetSeason: '2026/27',
    endpoint: ENDPOINT,
    initialUrl: INITIAL_URL,
    paginationPolicy: 'FOLLOW_OFFICIAL_PAGINATION_NEXT_URL_UNTIL_ABSENT',
    pageLimit: PAGE_LIMIT,
    sort: SORT_FIELD,
    observedAt: finalPass.observedAt,
    passCount: acquisition.passes.length,
    stablePair: acquisition.stablePair,
    pageCount: finalPass.pages.length,
    recordCount: events.length,
    duplicateEntityIds: finalPass.duplicateEntityIds,
    sourceSnapshotSha256: finalPass.snapshotSha256,
    eventsSha256: sha256(eventsContent),
    pageReceipts,
    temporalSemantics: {
      transferDatePromotedToEffectiveAt: false,
      contentDatePromotedToPublishedAt: false,
      observedAtPromotedToKnownAt: false,
    },
    identityJoinPerformed: false,
    historicalReplayAuthorized: false,
  }
  const manifestContent = canonicalJson(manifest)
  await writeFile(resolve(outputRoot, 'manifest.json'), manifestContent, 'utf8')
  return manifest
}

async function main() {
  const outputRoot = process.env.NEXUS_TRANSFER_OUTPUT_ROOT ?? '.nexus-transfer-events-current-v1'
  const acquisition = await acquireStableSnapshot()
  const manifest = await persistAcquisition(acquisition, outputRoot)
  process.stdout.write(`${JSON.stringify(manifest, null, 2)}\n`)
}

const executedDirectly = process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])
if (executedDirectly) {
  main().catch((error) => {
    console.error(error)
    process.exitCode = 1
  })
}
