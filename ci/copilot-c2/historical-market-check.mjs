import assert from 'node:assert/strict';

function percentileIncLinear(sortedValues, percentile) {
  if (sortedValues.length === 0) throw new Error('empty sample');
  if (percentile < 0 || percentile > 1) throw new Error('bad percentile');
  if (sortedValues.length === 1) return sortedValues[0];
  const position = (sortedValues.length - 1) * percentile;
  const lo = Math.floor(position);
  const hi = Math.ceil(position);
  if (lo === hi) return sortedValues[lo];
  const w = position - lo;
  return sortedValues[lo] + (sortedValues[hi] - sortedValues[lo]) * w;
}

function distribution(values) {
  if (values.length === 0) throw new Error('empty sample');
  const sorted = [...values].sort((a, b) => a - b);
  return {
    count: sorted.length,
    min: sorted[0],
    p25: percentileIncLinear(sorted, 0.25),
    median: percentileIncLinear(sorted, 0.5),
    p75: percentileIncLinear(sorted, 0.75),
    max: sorted.at(-1),
    mean: sorted.reduce((a, b) => a + b, 0) / sorted.length,
  };
}

function premiumPct(price, basePrice) {
  return ((price / basePrice) - 1) * 100;
}

const d = distribution([10, 20, 30, 40]);
assert.deepEqual(d, { count: 4, min: 10, p25: 17.5, median: 25, p75: 32.5, max: 40, mean: 25 });
assert.deepEqual(distribution([7]), { count: 1, min: 7, p25: 7, median: 7, p75: 7, max: 7, mean: 7 });
assert.throws(() => distribution([]), /empty sample/);
assert.throws(() => percentileIncLinear([1, 2], 1.1), /bad percentile/);

const prices = [40, 50, 60, 70];
const pd = distribution(prices);
assert.equal(pd.median, 55);
assert.equal(prices.filter((x) => x <= 60).length / prices.length, 0.75);
assert.ok(Math.abs(((60 / pd.median) - 1) * 100 - 9.090909090909083) < 1e-12);

const premiums = [premiumPct(40, 30), premiumPct(50, 40), premiumPct(70, 50)];
assert.equal(premiums.length, 3);
assert.ok(premiums.every(Number.isFinite));
assert.equal(premiumPct(20, 20), 0);

console.log('C2 public verification PASS');
