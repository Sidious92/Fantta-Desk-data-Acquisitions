#!/usr/bin/env node

import { mkdir, rm, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import {
  acquireStableSnapshot,
  canonicalJson,
  ENDPOINT,
  INITIAL_URL,
  materializeEvent,
  PAGE_LIMIT,
  sha256,
  SORT_FIELD,
} from './nexus-acquire-legaseriea-transfer-ledger-v1.mjs'

const outputRoot = process.env.NEXUS_TRANSFER_OUTPUT_ROOT ?? 'nexus-transfer-ledger-v1'
const acquisition = await acquireStableSnapshot()
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

process.stdout.write(`${JSON.stringify(manifest, null, 2)}\n`)
