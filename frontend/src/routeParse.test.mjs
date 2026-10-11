// node --test src/routeParse.test.mjs
import test from 'node:test';
import assert from 'node:assert/strict';
import { parseRoute, parseSteps } from './routeParse.js';

const leg = {
  Geometry: { LineString: [[77.21, 28.63], [77.212, 28.631], [77.215, 28.632]] },
  PedestrianLegDetails: {
    Summary: { Overview: { Distance: 420, Duration: 300 } },
    TravelSteps: [
      { Type: 'Depart', Distance: 120, Duration: 90, Instruction: 'Head north on Baba Kharak Singh Marg' },
      { Type: 'Turn', Distance: 250, Duration: 180, TurnStepDetails: { SteeringDirection: 'Left' } },
      { Type: 'Arrive', Distance: 0, Duration: 0 },
    ],
  },
};

test('parseRoute returns path, totals from legs, and steps', () => {
  const r = parseRoute({ Routes: [{ Legs: [leg] }] });
  assert.equal(r.path.length, 3);
  assert.equal(r.distance_m, 420);
  assert.equal(r.duration_s, 300);
  assert.equal(r.steps.length, 3);
});

test('route summary wins over leg sums when present', () => {
  const r = parseRoute({ Routes: [{ Summary: { Distance: 500, Duration: 360 }, Legs: [leg] }] });
  assert.equal(r.distance_m, 500);
  assert.equal(r.duration_s, 360);
});

test('steps use the instruction text, else a readable fallback', () => {
  const s = parseSteps([leg]);
  assert.equal(s[0].text, 'Head north on Baba Kharak Singh Marg');
  assert.equal(s[1].text, 'Turn left');
  assert.equal(s[2].text, 'Arrive');
  assert.deepEqual(s.map((x) => x.distance_m), [120, 250, 0]);
});

test('unusable responses give null or no steps', () => {
  assert.equal(parseRoute({}), null);
  assert.equal(parseRoute({ Routes: [{ Legs: [{ Geometry: { LineString: [[1, 2]] } }] }] }), null);
  assert.deepEqual(parseSteps([{ VehicleLegDetails: {} }]), []);
});
