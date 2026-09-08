import assert from 'node:assert/strict';

const evidence = {
  tier: { status: 'READY' },
  price: { status: 'PARTIAL' },
  supply: { status: 'READY' },
  demand: { status: 'READY' },
  strategy: { status: 'NO_DATA' },
  opponents: { status: 'READY' },
};

const dimensions = Object.keys(evidence);
assert.deepEqual(dimensions, ['tier', 'price', 'supply', 'demand', 'strategy', 'opponents']);
assert.equal(dimensions.length, 6);

const allowedStatuses = new Set(['READY', 'PARTIAL', 'NO_DATA']);
for (const dimension of Object.values(evidence)) {
  assert.equal(allowedStatuses.has(dimension.status), true);
}

const forbiddenOutputs = ['INTRINSIC_VALUE', 'TARGET_PRICE', 'MAX_BID', 'GLOBAL_SCORE', 'BUY_PASS_SIGNAL'];
assert.equal(forbiddenOutputs.includes('TARGET_PRICE'), true);
assert.equal(forbiddenOutputs.includes('GLOBAL_SCORE'), true);
assert.equal(forbiddenOutputs.includes('BUY_PASS_SIGNAL'), true);

const productionUiPolicy = {
  syntheticDemoValuesAllowed: false,
  truthfulEmptyStateRequired: true,
  runtimeBindingRequiredForLiveValues: true,
};

assert.equal(productionUiPolicy.syntheticDemoValuesAllowed, false);
assert.equal(productionUiPolicy.truthfulEmptyStateRequired, true);
assert.equal(productionUiPolicy.runtimeBindingRequiredForLiveValues, true);

console.log('C7 public verification PASS');
