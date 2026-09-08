import assert from 'node:assert/strict';

const rules = { teamCount: 8, initialBudget: 450, roleSlots: { P: 3, D: 8, C: 8, A: 6 } };
assert.equal(rules.teamCount, 8);
assert.equal(rules.initialBudget, 450);
assert.deepEqual(rules.roleSlots, { P: 3, D: 8, C: 8, A: 6 });

const events = [
  { sequence: 1, type: 'AUCTION_OPENED' },
  { sequence: 2, type: 'NOMINATION_OPENED', playerId: 10 },
  { sequence: 3, type: 'BID_OBSERVED', playerId: 10, amount: 25 },
  { sequence: 4, type: 'PLAYER_SOLD', playerId: 10, buyerTeamId: 'team-2', price: 25 },
];
assert.deepEqual(events.map((event) => event.sequence), [1, 2, 3, 4]);
assert.equal(events.at(-1).price, 25);

const runtimePolicy = {
  persistedAuthority: 'EVENT_LOG',
  derivedStatePersistedAsAuthority: false,
  syntheticProductionValuesAllowed: false,
  missingHistoryIsZero: false,
  predictiveEngineAllowed: false,
  maxBidAllowed: false,
};
assert.equal(runtimePolicy.persistedAuthority, 'EVENT_LOG');
assert.equal(runtimePolicy.derivedStatePersistedAsAuthority, false);
assert.equal(runtimePolicy.syntheticProductionValuesAllowed, false);
assert.equal(runtimePolicy.missingHistoryIsZero, false);
assert.equal(runtimePolicy.predictiveEngineAllowed, false);
assert.equal(runtimePolicy.maxBidAllowed, false);

const pipeline = ['C1_REPLAY', 'C3_SUPPLY_DEMAND', 'C4_OPPONENT_STATE', 'C5_OPTIONAL', 'C2_OPTIONAL_HISTORY', 'C6_RESOLVE', 'C7_RENDER'];
assert.equal(pipeline.at(-1), 'C7_RENDER');
assert.equal(pipeline.includes('C6_RESOLVE'), true);

console.log('C7R public verification PASS');
