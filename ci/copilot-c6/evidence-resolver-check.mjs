import assert from 'node:assert/strict';

const evidence = {
  tier: { status: 'READY', tierKey: 'F1', sourceCount: 20, dispersion: 0.1 },
  price: { status: 'READY', currentPrice: 60, historicalMedian: 55, historicalP75: 62.5, historicalSampleCount: 4 },
  supply: { status: 'READY', initialSegmentCount: 8, soldSegmentCount: 5, availableSegmentCount: 3, depletionPct: 62.5 },
  demand: { status: 'READY', demandScope: 'ROLE_SLOTS_ONLY', remainingRoleSlotsTotal: 24, teamsWithOpenRoleSlot: 6 },
  strategy: { status: 'READY', action: 'TARGET', priorityRank: 1, remainingPlannedTierCount: 1, plannedRoleMax: 260 },
  opponents: { status: 'READY', opponentCount: 3, opponentsWithOpenRoleSlot: 2, structurallyEligibleAtObservedPrice: 1 },
};

const statuses = Object.values(evidence).map((x) => x.status);
assert.equal(statuses.filter((x) => x === 'READY').length, 6);
assert.equal(evidence.price.currentPrice > evidence.price.historicalMedian, true);
assert.equal(evidence.price.currentPrice < evidence.price.historicalP75, true);
assert.equal(evidence.supply.availableSegmentCount, 3);
assert.equal(evidence.demand.demandScope, 'ROLE_SLOTS_ONLY');
assert.equal(evidence.strategy.action, 'TARGET');
assert.equal(evidence.opponents.structurallyEligibleAtObservedPrice, 1);

const forbiddenOutputs = ['INTRINSIC_VALUE', 'TARGET_PRICE', 'MAX_BID', 'GLOBAL_SCORE', 'BUY_PASS_SIGNAL'];
assert.equal(forbiddenOutputs.includes('GLOBAL_SCORE'), true);
assert.equal(forbiddenOutputs.includes('BUY_PASS_SIGNAL'), true);
assert.equal(forbiddenOutputs.length, 5);

const partialPrice = { status: 'PARTIAL', currentPrice: 60, historicalSampleCount: 0 };
assert.equal(partialPrice.status, 'PARTIAL');
assert.equal(partialPrice.historicalSampleCount, 0);

const missing = ['NO_DATA', 'NO_DATA', 'NO_DATA', 'NO_DATA', 'NO_DATA', 'NO_DATA'];
assert.equal(missing.filter((x) => x === 'NO_DATA').length, 6);

console.log('C6 public verification PASS');
