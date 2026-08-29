import assert from 'node:assert/strict'
import test from 'node:test'
import {
  ENDPOINT,
  INITIAL_URL,
  enumerateOnce,
  isStablePair,
  materializeEvent,
  normalizeTransferType,
  validateEnumerationUrl,
} from './nexus-acquire-legaseriea-transfer-ledger-v1.mjs'

function response(payload) {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json; charset=utf-8' },
    async json() { return payload },
  }
}

function item(id, overrides = {}) {
  return {
    _entityId: id,
    selfUrl: `${ENDPOINT}/${id}`,
    slug: `player-${id}`,
    title: `PLAYER ${id}`,
    fields: {
      playerName: 'PLAYER',
      playerSurname: id,
      transferDate: '2026-08-29T06:49:00Z',
      clubFrom: 'club a',
      clubTo: 'club b',
      transferType: 'Temporaneo',
      ...overrides.fields,
    },
    contentDate: '2026-08-29T07:00:00Z',
    lastUpdatedDate: '2026-08-29T07:01:00Z',
    entityCode: 'playertransfer',
    ...overrides,
  }
}

test('normalizza solo formule esplicite senza inventare semantica', () => {
  assert.equal(normalizeTransferType('Definitivo'), 'PERMANENT')
  assert.equal(normalizeTransferType('temporaneo'), 'LOAN')
  assert.equal(normalizeTransferType('rientro'), 'OTHER_EXPLICIT')
  assert.equal(normalizeTransferType(null), 'UNRESOLVED')
})

test('rifiuta nextUrl fuori dalla DAPI ufficiale', () => {
  assert.throws(
    () => validateEnumerationUrl('https://example.com/v2/content/it-IT/playertransfers?$limit=10&$sort=fields.transferDate&$skip=10', { previousSkip: 0 }),
    /host non ammesso/,
  )
})

test('enumera seguendo esclusivamente pagination.nextUrl fino alla sua assenza', async () => {
  const secondUrl = `${ENDPOINT}?$limit=10&$sort=fields.transferDate&$skip=10`
  const payloads = new Map([
    [INITIAL_URL, { pagination: { nextUrl: secondUrl, maxItems: 100 }, meta: { generatedAt: '2026-08-29T12:00:00Z' }, items: [item('1')] }],
    [secondUrl, { pagination: { previousUrl: INITIAL_URL, maxItems: 100 }, meta: { generatedAt: '2026-08-29T12:00:01Z' }, items: [item('2')] }],
  ])
  const fetchFn = async (url) => {
    assert(payloads.has(url), `URL inatteso ${url}`)
    return response(payloads.get(url))
  }

  const result = await enumerateOnce({ fetchFn, observedAt: '2026-08-29T12:01:00Z' })
  assert.equal(result.pages.length, 2)
  assert.equal(result.uniqueItemCount, 2)
  assert.deepEqual(result.duplicateEntityIds, [])
})

test('duplica entity id viene rilevato e impedisce una coppia stabile', async () => {
  const secondUrl = `${ENDPOINT}?$limit=10&$sort=fields.transferDate&$skip=10`
  const payloads = new Map([
    [INITIAL_URL, { pagination: { nextUrl: secondUrl }, items: [item('1')] }],
    [secondUrl, { pagination: {}, items: [item('1')] }],
  ])
  const fetchFn = async (url) => response(payloads.get(url))
  const left = await enumerateOnce({ fetchFn, observedAt: '2026-08-29T12:01:00Z' })
  const right = await enumerateOnce({ fetchFn, observedAt: '2026-08-29T12:02:00Z' })
  assert.deepEqual(left.duplicateEntityIds, ['1'])
  assert.equal(isStablePair(left, right), false)
})

test('materializzazione conserva date sorgente ma lascia null le semantiche temporali non provate', () => {
  const event = materializeEvent(item('abc'), '2026-08-29T12:05:00Z')
  assert.equal(event.transferTypeNormalized, 'LOAN')
  assert.equal(event.sourceTemporalFields.transferDate, '2026-08-29T06:49:00Z')
  assert.equal(event.effectiveAt, null)
  assert.equal(event.publishedAt, null)
  assert.equal(event.knownAt, null)
  assert.equal(event.observedAt, '2026-08-29T12:05:00Z')
})

test('club di origine mancante nella fonte ufficiale resta null e SOURCE_MISSING', () => {
  const source = item('missing-origin')
  delete source.fields.clubFrom
  const event = materializeEvent(source, '2026-08-29T12:06:00Z')
  assert.equal(event.originClubSource, null)
  assert.equal(event.destinationClubSource, 'club b')
  assert.equal(event.sourceFieldStatus.originClub, 'SOURCE_MISSING')
  assert.equal(event.sourceFieldStatus.destinationClub, 'PRESENT')
  assert.equal(event.sourceRecordRaw.fields.clubFrom, undefined)
})

test('transfer type e transferDate mancanti restano esplicitamente unresolved/source-missing', () => {
  const source = item('missing-optional')
  delete source.fields.transferType
  delete source.fields.transferDate
  const event = materializeEvent(source, '2026-08-29T12:07:00Z')
  assert.equal(event.transferTypeSource, null)
  assert.equal(event.transferTypeNormalized, 'UNRESOLVED')
  assert.equal(event.sourceTemporalFields.transferDate, null)
  assert.equal(event.sourceFieldStatus.transferType, 'SOURCE_MISSING')
  assert.equal(event.sourceFieldStatus.transferDate, 'SOURCE_MISSING')
  assert.equal(event.effectiveAt, null)
  assert.equal(event.publishedAt, null)
  assert.equal(event.knownAt, null)
})

test('club di destinazione resta requisito strutturale fail-closed', () => {
  const source = item('missing-destination')
  delete source.fields.clubTo
  assert.throws(
    () => materializeEvent(source, '2026-08-29T12:08:00Z'),
    /clubTo mancante/,
  )
})
