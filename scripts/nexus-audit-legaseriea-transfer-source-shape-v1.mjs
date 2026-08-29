#!/usr/bin/env node

import { mkdir, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import {
  INITIAL_URL,
  canonicalJson,
  sha256,
  validateEnumerationUrl,
} from './nexus-acquire-legaseriea-transfer-ledger-v1.mjs'

const outputRoot = process.env.NEXUS_TRANSFER_DIAGNOSTIC_OUTPUT_ROOT ?? 'nexus-transfer-source-shape-v1'
const observedAt = new Date().toISOString()
let nextUrl = INITIAL_URL
let previousSkip = -1
const items = []
const pages = []
const seen = new Set()
const duplicateEntityIds = new Set()

while (nextUrl) {
  const { skip } = validateEnumerationUrl(nextUrl, { previousSkip })
  previousSkip = skip
  const response = await fetch(nextUrl, { method: 'GET', headers: { accept: 'application/json' }, redirect: 'error' })
  if (!response.ok) throw new Error(`Source-shape audit: HTTP ${response.status} per ${nextUrl}`)
  const payload = await response.json()
  if (!Array.isArray(payload?.items)) throw new Error('Source-shape audit: items[] mancante')
  if (!payload?.pagination || typeof payload.pagination !== 'object') throw new Error('Source-shape audit: pagination mancante')

  pages.push({
    index: pages.length,
    skip,
    requestUrl: nextUrl,
    itemCount: payload.items.length,
    generatedAt: payload.meta?.generatedAt ?? null,
    sha256: sha256(canonicalJson(payload)),
  })

  for (const item of payload.items) {
    const id = String(item?._entityId ?? '').trim()
    if (id && seen.has(id)) duplicateEntityIds.add(id)
    if (id) seen.add(id)
    items.push(item)
  }

  if (payload.items.length === 0) {
    if (payload.pagination.nextUrl) throw new Error('Source-shape audit: pagina vuota con nextUrl presente')
    break
  }
  if (!payload.pagination.nextUrl) break
  validateEnumerationUrl(payload.pagination.nextUrl, { previousSkip })
  nextUrl = payload.pagination.nextUrl
}

const checks = {
  missingEntityId: (item) => !String(item?._entityId ?? '').trim(),
  wrongEntityCode: (item) => item?.entityCode !== 'playertransfer',
  missingPlayerNameAndTitle: (item) => {
    const fieldsName = [item?.fields?.playerName, item?.fields?.playerSurname]
      .map((v) => String(v ?? '').trim()).filter(Boolean).join(' ')
    return !fieldsName && !String(item?.title ?? '').trim()
  },
  missingClubFrom: (item) => !String(item?.fields?.clubFrom ?? '').trim(),
  missingClubTo: (item) => !String(item?.fields?.clubTo ?? '').trim(),
  missingTransferType: (item) => !String(item?.fields?.transferType ?? '').trim(),
  missingRole: (item) => !String(item?.fields?.role ?? '').trim(),
  missingTransferDate: (item) => !String(item?.fields?.transferDate ?? '').trim(),
  missingContentDate: (item) => !String(item?.contentDate ?? '').trim(),
  missingLastUpdatedDate: (item) => !String(item?.lastUpdatedDate ?? '').trim(),
}

const missingness = {}
const anomalies = []
for (const [name, check] of Object.entries(checks)) {
  const matching = items.filter(check)
  missingness[name] = matching.length
  for (const item of matching) {
    anomalies.push({ check: name, entityId: item?._entityId ?? null, raw: item })
  }
}

const uniqueAnomalyRows = new Map()
for (const anomaly of anomalies) {
  const key = `${anomaly.check}:${anomaly.entityId ?? sha256(canonicalJson(anomaly.raw))}`
  uniqueAnomalyRows.set(key, anomaly)
}

const audit = {
  schema: 'NEXUS_TRANSFER_EVENT_SOURCE_SHAPE_AUDIT_V1',
  status: 'DIAGNOSTIC_ONLY_NO_AUTHORITY_FREEZE',
  observedAt,
  pageCount: pages.length,
  rawRecordCount: items.length,
  uniqueEntityIdCount: seen.size,
  duplicateEntityIds: [...duplicateEntityIds].sort(),
  missingness,
  pages,
  anomalies: [...uniqueAnomalyRows.values()],
  scientificBoundary: {
    canonicalTransferLedgerMaterialized: false,
    identityJoinPerformed: false,
    historicalReplayAuthorized: false,
    modelTrainingPerformed: false,
  },
}

await mkdir(resolve(outputRoot), { recursive: true })
await writeFile(resolve(outputRoot, 'source-shape-audit-v1.json'), canonicalJson(audit), 'utf8')
process.stdout.write(`${JSON.stringify({
  status: audit.status,
  pageCount: audit.pageCount,
  rawRecordCount: audit.rawRecordCount,
  uniqueEntityIdCount: audit.uniqueEntityIdCount,
  duplicateEntityIds: audit.duplicateEntityIds,
  missingness: audit.missingness,
}, null, 2)}\n`)
