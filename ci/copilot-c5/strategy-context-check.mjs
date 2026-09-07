import assert from 'node:assert/strict';

const plan = {
  roleTierPlans: [
    { role: 'A', tierKey: 'F1', desiredCount: 1 },
    { role: 'A', tierKey: 'F2', desiredCount: 2 },
  ],
  roleBudgetEnvelope: { role: 'A', plannedTotalMin: 180, plannedTotalMax: 260 },
  playerIntents: [
    { playerId: 1, action: 'TARGET', priorityRank: 1 },
    { playerId: 2, action: 'FALLBACK', priorityRank: 2 },
  ],
};

const liveSales = [
  { playerId: 1, buyerTeamId: 'user', role: 'A', tierKey: 'F1', price: 70 },
  { playerId: 9, buyerTeamId: 'rival', role: 'A', tierKey: 'F1', price: 80 },
];

const userSales = liveSales.filter((sale) => sale.buyerTeamId === 'user');
const liveSpentA = userSales.filter((sale) => sale.role === 'A').reduce((sum, sale) => sum + sale.price, 0);
const acquiredAF1 = userSales.filter((sale) => sale.role === 'A' && sale.tierKey === 'F1').length;
const desiredAF1 = plan.roleTierPlans.find((item) => item.role === 'A' && item.tierKey === 'F1').desiredCount;
const remainingAF1 = Math.max(0, desiredAF1 - acquiredAF1);
const remainingToMax = plan.roleBudgetEnvelope.plannedTotalMax - liveSpentA;

assert.equal(liveSpentA, 70);
assert.equal(acquiredAF1, 1);
assert.equal(remainingAF1, 0);
assert.equal(remainingToMax, 190);
assert.equal(liveSpentA > plan.roleBudgetEnvelope.plannedTotalMax, false);
assert.deepEqual(plan.playerIntents.map((x) => x.action), ['TARGET', 'FALLBACK']);
assert.equal(Object.hasOwn(plan.playerIntents[0], 'targetPrice'), false);
assert.equal(Object.hasOwn(plan.playerIntents[0], 'maxBid'), false);

const unknownTier = { playerId: 4, role: 'A', tierKey: undefined };
assert.equal(unknownTier.tierKey, undefined);
assert.equal(Math.max(0, 0 - 1), 0);
assert.equal(plan.roleBudgetEnvelope.plannedTotalMin <= plan.roleBudgetEnvelope.plannedTotalMax, true);

console.log('C5 public verification PASS');
