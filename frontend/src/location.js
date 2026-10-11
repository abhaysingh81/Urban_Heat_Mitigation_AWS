// Amazon Location Service (optional). The API key is created by the stack when it is deployed
// with ENABLE_LOCATION_MAP=1 and is restricted to the site's own origin; without it the app
// falls back to the CARTO basemap and straight-line walking estimates.
export const LOCATION_KEY = import.meta.env.VITE_AWS_LOCATION_KEY || '';
export const LOCATION_REGION = import.meta.env.VITE_AWS_REGION || 'us-east-1';

// CalculateRoutes response -> { path: [[lon, lat], …], distance_m, duration_s }, or null if unusable.
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
  return { path, distance_m: Math.round(distance), duration_s: Math.round(duration) };
}

// Walking route between two { lat, lon } points. The position goes straight from the browser to
// Amazon Location; it is never sent to this app's API or logged. Throws when no route is available.
export async function walkingRoute(origin, destination) {
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
