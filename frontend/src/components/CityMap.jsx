import { GeoJsonLayer } from '@deck.gl/layers';
import BaseMap from './BaseMap';

/**
 * Grid map: one polygon per 500 m cell, coloured by `colorOf(properties)` (an RGB array, or null
 * to hide the cell). `tooltipOf(properties)` returns a string. `onPick(properties)` on click.
 */
export default function CityMap({ grid, center, colorOf, tooltipOf, onPick, height = 380, updateKey }) {
  const layer = new GeoJsonLayer({
    id: 'cells', data: grid, pickable: true, stroked: false, filled: true,
    getFillColor: (f) => { const c = colorOf(f.properties); return c ? [...c, 255] : [0, 0, 0, 0]; },
    updateTriggers: { getFillColor: [updateKey] },
    onClick: onPick ? (info) => info.object && onPick(info.object.properties) : undefined,
  });
  const [lon, lat] = center || [77.2, 28.61];
  return (
    <div style={{ position: 'relative', height, borderRadius: 12, overflow: 'hidden' }}>
      <BaseMap initialViewState={{ longitude: lon, latitude: lat, zoom: 9.6 }} layers={[layer]} boundary={grid?.boundary}
        getTooltip={({ object }) => (object && tooltipOf ? tooltipOf(object.properties) : null)} />
    </div>
  );
}
