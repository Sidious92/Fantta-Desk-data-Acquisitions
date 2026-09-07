import assert from 'node:assert/strict';

const players = [
  { playerId: 1, role: 'A', active: true, tierKey: 'F1' },
  { playerId: 2, role: 'A', active: true, tierKey: 'F1' },
  { playerId: 3, role: 'A', active: true, tierKey: 'F2' },
  { playerId: 4, role: 'A', active: true },
  { playerId: 5, role: 'A', active: false, tierKey: 'F1' },
  { playerId: 6, role: 'C', active: true, tierKey: 'F1' },
];

const sold = new Set([1]);
const remainingSlots = [5, 6];

const activeRole = players.filter((p) => p.active && p.role === 'A');
const segment = activeRole.filter((p) => p.tierKey === 'F1');
const soldSegment = segment.filter((p) => sold.has(p.playerId));
const availableSegment = segment.filter((p) => !sold.has(p.playerId));
const availableRole = activeRole.filter((p) => !sold.has(p.playerId));
const remainingRoleSlotsTotal = remainingSlots.reduce((a, b) => a + b, 0);
const teamsWithOpenRoleSlot = remainingSlots.filter((slots) => slots > 0).length;

assert.equal(segment.length, 2);
assert.equal(soldSegment.length, 1);
assert.equal(availableSegment.length, 1);
assert.deepEqual(availableSegment.map((p) => p.playerId), [2]);
assert.equal((soldSegment.length / segment.length) * 100, 50);
assert.equal(availableRole.length, 3);
assert.equal(availableRole.filter((p) => p.tierKey === undefined).length, 1);
assert.equal(remainingRoleSlotsTotal, 11);
assert.equal(teamsWithOpenRoleSlot, 2);
assert.equal(availableSegment.length / remainingRoleSlotsTotal, 1 / 11);
assert.equal(availableRole.length / remainingRoleSlotsTotal, 3 / 11);

console.log('C3 public verification PASS');
