export const F1_SCHEMA_VERSION = 'nexus-input-v1.1-f1-raw-stint-1.0.0'
export const MISSING_REASONS = Object.freeze([
  'NOT_COLLECTED',
  'SOURCE_NO_COVERAGE',
  'NOT_APPLICABLE',
  'UNKNOWN',
  'MAPPING_UNRESOLVED',
])

export const QUARANTINE_REASONS = Object.freeze([
  'MAPPING_UNRESOLVED',
  'STINT_UNRESOLVED',
  'TEMPORAL_UNVERIFIED',
  'SOURCE_AGGREGATE_MULTI_CLUB',
  'SOURCE_AGGREGATE_FINAL_CLUB_ONLY',
])

export const RAW_METRICS = Object.freeze({
  games: 'count', appearances: 'count', starts: 'count', substituteAppearances: 'count', minutes: 'minutes',
  goals: 'count', nonPenaltyGoals: 'count', assists: 'count', xG: 'expected-goals units', npxG: 'expected-goals units',
  xA: 'expected-assist units', shots: 'count', keyPasses: 'count', xGChain: 'expected-goals units', xGBuildup: 'expected-goals units',
  penaltiesTaken: 'count', penaltiesScored: 'count', averageVote: 'provider vote scale', appearancesWithVote: 'count',
  teamGoals: 'count', teamNonPenaltyGoals: 'count', teamXG: 'expected-goals units', teamNpxG: 'expected-goals units', teamXA: 'expected-assist units',
})

function fail(message) { throw new Error(`Nexus F1 RAW/Stint contract: ${message}`) }
function assert(condition, message) { if (!condition) fail(message) }
function text(v) { return typeof v === 'string' && v.trim().length > 0 }
function iso(v) { return text(v) && Number.isFinite(Date.parse(v)) }
function sha(v) { return text(v) && /^[a-f0-9]{40,64}$/u.test(v) }

function validateObservation(name, observation, context) {
  assert(Object.hasOwn(RAW_METRICS, name), `${context}: metrica RAW non registrata: ${name}`)
  assert(observation && typeof observation === 'object' && !Array.isArray(observation), `${context}.${name} non valido`)
  assert(text(observation.sourceField), `${context}.${name}.sourceField obbligatorio`)
  assert(text(observation.unit), `${context}.${name}.unit obbligatoria`)
  assert(text(observation.semantics), `${context}.${name}.semantics obbligatoria`)
  assert(observation.transformation === 'NONE', `${context}.${name}: RAW vieta trasformazioni`)
  assert(!/per\s*90|\/90|pooled|stable|shrink|imput/i.test(observation.sourceField), `${context}.${name}: sourceField appare trasformato`)
  if (observation.value === null) assert(MISSING_REASONS.includes(observation.missingReason), `${context}.${name}: NULL richiede missingReason tipizzato`)
  else {
    assert(observation.missingReason === null, `${context}.${name}: valore osservato non può avere missingReason`)
    assert(typeof observation.value === 'number' && Number.isFinite(observation.value), `${context}.${name}.value deve essere numero finito o NULL`)
    assert(observation.value >= 0, `${context}.${name}: valore negativo vietato`)
  }
}

export function validateRawStintRecord(record, index = 0) {
  const c = `records[${index}]`
  assert(record && typeof record === 'object' && !Array.isArray(record), `${c} non valido`)
  assert(record.schemaVersion === F1_SCHEMA_VERSION, `${c}.schemaVersion non valido`)
  assert(record.protocolVersion === '1.1', `${c}.protocolVersion non valido`)
  assert(['ANALYTIC_ELIGIBLE', 'QUARANTINED'].includes(record.recordStatus), `${c}.recordStatus non valido`)
  const t = record.technicalKey
  assert(t && typeof t === 'object', `${c}.technicalKey mancante`)
  for (const key of ['provider', 'competition', 'sourceRecordId', 'sourceVersion']) assert(text(t[key]), `${c}.technicalKey.${key} obbligatorio`)
  const sd = record.sourceDimensions
  assert(sd && typeof sd === 'object' && !Array.isArray(sd), `${c}.sourceDimensions mancante`)
  assert(text(sd.season), `${c}.sourceDimensions.season obbligatoria`)
  assert(text(sd.competition), `${c}.sourceDimensions.competition obbligatoria`)
  assert(sd.club === null || text(sd.club), `${c}.sourceDimensions.club non valido`)
  const a = record.analyticKey
  assert(a && typeof a === 'object', `${c}.analyticKey mancante`)
  assert(text(a.season), `${c}.analyticKey.season obbligatoria`)
  assert(text(a.league), `${c}.analyticKey.league obbligatoria`)
  if (record.recordStatus === 'ANALYTIC_ELIGIBLE') {
    assert(text(a.club), `${c}: ANALYTIC_ELIGIBLE richiede club`)
    assert(text(a.stintId), `${c}: ANALYTIC_ELIGIBLE richiede stintId`)
    assert(Number.isInteger(a.stintOrdinal) && a.stintOrdinal >= 1, `${c}: ANALYTIC_ELIGIBLE richiede stintOrdinal intero >=1`)
  } else {
    assert(a.club === null || text(a.club), `${c}.analyticKey.club non valido`)
    assert(a.stintId === null || text(a.stintId), `${c}.analyticKey.stintId non valido`)
    assert(a.stintOrdinal === null || (Number.isInteger(a.stintOrdinal) && a.stintOrdinal >= 1), `${c}.analyticKey.stintOrdinal non valido`)
  }
  assert(Array.isArray(record.quarantineReasons), `${c}.quarantineReasons deve essere array`)
  if (record.recordStatus === 'QUARANTINED') {
    assert(record.quarantineReasons.length > 0, `${c}: QUARANTINED richiede almeno un motivo`)
    for (const reason of record.quarantineReasons) assert(QUARANTINE_REASONS.includes(reason), `${c}: quarantine reason non supportato: ${reason}`)
  } else assert(record.quarantineReasons.length === 0, `${c}: ANALYTIC_ELIGIBLE non può avere quarantineReasons`)
  const identity = record.identity
  assert(identity && typeof identity === 'object', `${c}.identity mancante`)
  assert(text(identity.sourcePlayerId), `${c}.identity.sourcePlayerId obbligatorio`)
  assert(['VERIFIED', 'MAPPING_UNRESOLVED'].includes(identity.mappingStatus), `${c}.identity.mappingStatus non valido`)
  if (record.recordStatus === 'ANALYTIC_ELIGIBLE') {
    assert(identity.mappingStatus === 'VERIFIED', `${c}: ANALYTIC_ELIGIBLE richiede mapping VERIFIED`)
    assert(text(a.playerId), `${c}: ANALYTIC_ELIGIBLE richiede playerId canonico`)
  }
  if (identity.mappingStatus === 'MAPPING_UNRESOLVED') {
    assert(record.recordStatus === 'QUARANTINED', `${c}: mapping unresolved deve essere quarantinato`)
    assert(a.playerId === null, `${c}: mapping unresolved richiede playerId NULL`)
    assert(record.quarantineReasons.includes('MAPPING_UNRESOLVED'), `${c}: mapping unresolved richiede quarantine reason`)
  }
  const p = record.provenance
  assert(p && typeof p === 'object', `${c}.provenance mancante`)
  assert(iso(p.capturedAt), `${c}.provenance.capturedAt non valido`)
  assert(sha(p.sourceHash), `${c}.provenance.sourceHash non valido`)
  assert(['VERIFIED_AS_OF', 'CURRENT_ONLY', 'UNKNOWN'].includes(p.temporalStatus), `${c}.provenance.temporalStatus non valido`)
  if (p.temporalStatus === 'VERIFIED_AS_OF') {
    assert(iso(p.availableAt), `${c}: VERIFIED_AS_OF richiede availableAt`)
    assert(Array.isArray(p.availableAtEvidenceRefs) && p.availableAtEvidenceRefs.length > 0 && p.availableAtEvidenceRefs.every(text), `${c}: VERIFIED_AS_OF richiede evidenza availableAt`)
    assert(Date.parse(p.availableAt) <= Date.parse(p.capturedAt), `${c}: availableAt successivo a capturedAt`)
  } else assert(p.availableAt === null, `${c}: temporalStatus ${p.temporalStatus} richiede availableAt NULL`)
  assert(text(record.scope), `${c}.scope obbligatorio`)
  assert(text(record.providerRules), `${c}.providerRules obbligatorio`)
  assert(record.observations && typeof record.observations === 'object' && !Array.isArray(record.observations), `${c}.observations mancante`)
  assert(Object.keys(record.observations).length > 0, `${c}.observations vuoto`)
  for (const [name, observation] of Object.entries(record.observations)) validateObservation(name, observation, `${c}.observations`)
  const v = name => record.observations[name]?.value
  if (v('starts') != null && v('appearances') != null) assert(v('starts') <= v('appearances'), `${c}: starts > appearances`)
  if (v('nonPenaltyGoals') != null && v('goals') != null) assert(v('nonPenaltyGoals') <= v('goals'), `${c}: nonPenaltyGoals > goals`)
  if (v('penaltiesScored') != null && v('penaltiesTaken') != null) assert(v('penaltiesScored') <= v('penaltiesTaken'), `${c}: penaltiesScored > penaltiesTaken`)
  if (v('npxG') != null && v('xG') != null && Number.isFinite(record.providerNpxgXgTolerance)) assert(v('npxG') <= v('xG') + record.providerNpxgXgTolerance, `${c}: npxG > xG oltre tolleranza provider`)
  return true
}
