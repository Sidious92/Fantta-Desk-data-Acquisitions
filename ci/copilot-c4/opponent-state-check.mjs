import assert from 'node:assert/strict';

const currentTeam = {
  initialBudget: 450,
  spent: 100,
  remainingBudget: 350,
  roleCounts: { P: 0, D: 0, C: 1, A: 1 },
  remainingSlots: { P: 3, D: 8, C: 7, A: 5 },
};

const liveSales = [
  { playerId: 1, role: 'A', price: 70, tierKey: 'F1' },
  { playerId: 2, role: 'C', price: 30, tierKey: 'F2' },
];

const aliases = ['negromanti', 'er-tavernello'];
const historical = [
  { buyerTeamId: 'er-tavernello', season: '2023-24', auctionId: 'a23', role: 'A', tierKey: 'F1', price: 80 },
  { buyerTeamId: 'negromanti', season: '2024-25', auctionId: 'a24', role: 'A', tierKey: 'F1', price: 100 },
  { buyerTeamId: 'negromanti', season: '2024-25', auctionId: 'a24', role: 'C', tierKey: 'F2', price: 35 },
  { buyerTeamId: 'rival', season: '2024-25', auctionId: 'a24', role: 'A', tierKey: 'F1', price: 60 },
];

const matched = historical.filter((sale) => aliases.includes(sale.buyerTeamId));
const historicalSpend = matched.reduce((sum, sale) => sum + sale.price, 0);
const liveASpend = liveSales.filter((sale) => sale.role === 'A').reduce((sum, sale) => sum + sale.price, 0);
const liveF1Count = liveSales.filter((sale) => sale.tierKey === 'F1').length;
const budgetSpentPct = (currentTeam.spent / currentTeam.initialBudget) * 100;
const structuralEligibility = currentTeam.remainingSlots.A > 0 && currentTeam.remainingBudget >= 120;

assert.equal(matched.length, 3);
assert.equal(new Set(matched.map((sale) => sale.season)).size, 2);
assert.equal(historicalSpend, 215);
assert.equal(liveASpend, 70);
assert.equal(liveF1Count, 1);
assert.equal(currentTeam.remainingBudget, 350);
assert.ok(Math.abs(budgetSpentPct - 22.22222222222222) < 1e-12);
assert.equal(structuralEligibility, true);

const unknownTierSales = [{ playerId: 4, role: 'D', price: 10, tierKey: undefined }];
assert.equal(unknownTierSales.filter((sale) => sale.tierKey === undefined).length, 1);

console.log('C4 public verification PASS');
