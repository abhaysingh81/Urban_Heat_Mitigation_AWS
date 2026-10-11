// Pure helpers for Amazon Location Routes V2 responses (no browser or Vite globals, so they can be
// unit-tested with `node --test`). Field names follow the CalculateRoutes API reference:
// Routes[].Legs[].Geometry.LineString and Routes[].Legs[].PedestrianLegDetails.TravelSteps[].

// One walking step for display. `Instruction` is only returned with TravelStepType "Default";
// without it we build a short fallback from the step type and distance.
const FALLBACK = {
  Depart: 'Start walking', Arrive: 'Arrive', Continue: 'Continue', Keep: 'Keep going',
  Turn: 'Turn', RoundaboutEnter: 'Enter the roundabout', RoundaboutExit: 'Leave the roundabout',
  RoundaboutPass: 'Go through the roundabout',
};

export function parseSteps(legs) {
  const steps = [];
  for (const leg of legs || []) {
    for (const s of leg?.PedestrianLegDetails?.TravelSteps || []) {
      let text = s.Instruction;
      if (!text) {
        const dir = s.TurnStepDetails?.SteeringDirection;
        text = FALLBACK[s.Type] || s.Type || 'Continue';
        if (s.Type === 'Turn' && dir) text = `Turn ${String(dir).toLowerCase()}`;
      }
      steps.push({ type: s.Type, text, distance_m: Math.round(s.Distance || 0), duration_s: Math.round(s.Duration || 0) });
    }
  }
  return steps;
}

// CalculateRoutes response -> { path: [[lon, lat], …], distance_m, duration_s, steps }, or null if unusable.
export function parseRoute(json) {
  const route = json?.Routes?.[0];
  if (!route) return null;
  const legs = route.Legs || [];
  const path = legs.flatMap((leg) => leg?.Geometry?.LineString || []);
  if (path.length < 2) return null;
  const legSum = (field) => legs.reduce((sum, leg) => {
    const details = leg.PedestrianLegDetails || leg.VehicleLegDetails || leg.FerryLegDetails;
    return sum + (details?.Summary?.Overview?.[field] || 0);
  }, 0);
  const distance = route.Summary?.Distance ?? legSum('Distance');
  const duration = route.Summary?.Duration ?? legSum('Duration');
  return { path, distance_m: Math.round(distance), duration_s: Math.round(duration), steps: parseSteps(legs) };
}
