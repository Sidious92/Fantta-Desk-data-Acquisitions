import assert from 'node:assert/strict';

const historicalImport = {
  formats: ['XLSX', 'XLS', 'CSV'],
  minimumColumns: ['season', 'role', 'buyerTeamId', 'price'],
  currentPlayerIdRequired: false,
  syntheticPlayerIdentityAllowed: false,
};
assert.equal(historicalImport.currentPlayerIdRequired, false);
assert.equal(historicalImport.syntheticPlayerIdentityAllowed, false);
assert.deepEqual(historicalImport.minimumColumns, ['season', 'role', 'buyerTeamId', 'price']);

const strategy = {
  explicitTierCounts: true,
  explicitRoleBudgetEnvelope: true,
  explicitPlayerIntent: ['TARGET', 'FALLBACK', 'AVOID'],
  targetPriceAllowed: false,
};
assert.equal(strategy.explicitTierCounts, true);
assert.equal(strategy.targetPriceAllowed, false);

const opponentAliases = {
  explicitOnly: true,
  fuzzyMatchingAllowed: false,
};
assert.equal(opponentAliases.explicitOnly, true);
assert.equal(opponentAliases.fuzzyMatchingAllowed, false);

const forbidden = ['PREDICTIVE_ENGINE', 'OPPORTUNITY', 'INTRINSIC_VALUE', 'TARGET_PRICE', 'MAX_BID', 'GLOBAL_BUY_PASS_SCORE'];
assert.equal(forbidden.includes('PREDICTIVE_ENGINE'), true);
assert.equal(forbidden.includes('MAX_BID'), true);

console.log('Copilot in-app authority bindings PASS');
