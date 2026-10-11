// Amazon Location Service (optional). The API key is created by the stack when it is deployed
// with ENABLE_LOCATION_MAP=1 and is restricted to the site's own origin; without it the app
// falls back to the CARTO basemap and straight-line walking estimates.
import { parseRoute } from './routeParse';

export { parseRoute, parseSteps } from './routeParse';
export const LOCATION_KEY = import.meta.env.VITE_AWS_LOCATION_KEY || '';
export const LOCATION_REGION = import.meta.env.VITE_AWS_REGION || 'us-east-1';

// Walking route between two { lat, lon } points. The position goes straight from the browser to
// Amazon Location; it is never sent to this app's API or logged. Throws when no route is available.
export async function walkingRoute(origin, destination, languages = ['en']) {
  if (!LOCATION_KEY) throw new Error('no location key');
  const res = await fetch(
    `https://routes.geo.${LOCATION_REGION}.amazonaws.com/v2/routes?key=${encodeURIComponent(LOCATION_KEY)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        Origin: [origin.lon, origin.lat],
        Destination: [destination.lon, destination.lat],
        TravelMode: 'Pedestrian',
        LegGeometryFormat: 'Simple',
        // step-by-step text: Instruction is only filled for TravelStepType "Default"
        TravelStepType: 'Default',
        LegAdditionalFeatures: ['TravelStepInstructions'],
        Languages: languages,
        InstructionsMeasurementSystem: 'Metric',
      }),
    });
  if (!res.ok) throw new Error(`route request failed (${res.status})`);
  const route = parseRoute(await res.json());
  if (!route) throw new Error('no route found');
  return route;
}

// Camera that fits a path into a small (about 240 px high) map with room around both ends.
// At zoom z the world is 512 * 2^z px wide, so log2(80 / span) puts the longer side of the
// path at roughly half the map's height.
export function viewForPath(path) {
  const lons = path.map((p) => p[0]);
  const lats = path.map((p) => p[1]);
  const span = Math.max(Math.max(...lons) - Math.min(...lons), Math.max(...lats) - Math.min(...lats), 0.002);
  return {
    longitude: (Math.max(...lons) + Math.min(...lons)) / 2,
    latitude: (Math.max(...lats) + Math.min(...lats)) / 2,
    zoom: Math.max(10, Math.min(16.5, Math.log2(80 / span))),
    pitch: 0, bearing: 0,
  };
}
