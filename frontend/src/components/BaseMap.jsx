import { useCallback, useMemo, useState } from 'react';
import { GeoJsonLayer } from '@deck.gl/layers';
import Map, { useControl } from 'react-map-gl/maplibre';
import { MapboxOverlay } from '@deck.gl/mapbox';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useTheme } from '../ThemeContext';

const MAP_STYLE_DARK = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';
const MAP_STYLE_LIGHT = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

function DeckOverlay(props) {
  const overlay = useControl(() => new MapboxOverlay(props));
  overlay.setProps(props);
  return null;
}

/**
 * Basemap + deck.gl layers drawn *inside* the map (interleaved), just below the
 * basemap's first label layer, so place names stay readable on top of the data.
 * Drop-in for <DeckGL initialViewState layers getTooltip><Map/></DeckGL>.
 *
 * Zooming in fades the data (opacity 0.85 at city scale -> 0.35 at street scale) so
 * neighbourhood names and streets stay readable. `boundary` (GeoJSON) draws the city outline.
 */
const fade = (z) => Math.max(0.35, Math.min(0.85, 0.85 - (z - 10.5) * 0.15));

export default function BaseMap({ initialViewState, layers, getTooltip, boundary }) {
  const { theme } = useTheme();
  const [zoom, setZoom] = useState(initialViewState?.zoom ?? 10);
  const onMove = useCallback((e) => {
    const z = Math.round(e.viewState.zoom * 4) / 4;  // update in quarter steps, not every frame
    setZoom((old) => (old === z ? old : z));
  }, []);
  const outline = useMemo(() => (boundary ? new GeoJsonLayer({
    id: 'city-boundary', data: boundary, filled: false, stroked: true, pickable: false,
    getLineColor: theme === 'light' ? [40, 40, 60, 220] : [235, 235, 245, 220],
    lineWidthUnits: 'pixels', getLineWidth: 2,
  }) : null), [boundary, theme]);
  const style = theme === 'light' ? MAP_STYLE_LIGHT : MAP_STYLE_DARK;
  const [labelLayer, setLabelLayer] = useState(null);

  const onLoad = useCallback((e) => {
    const map = e.target;
    const symbols = map.getStyle().layers.filter((l) => l.type === 'symbol');
    // Stronger label outline + contrast so place names stay readable over any heat colour.
    const light = theme === 'light';
    symbols.filter((l) => l.layout && l.layout['text-field']).forEach((l) => {
      try {
        map.setPaintProperty(l.id, 'text-halo-color', light ? 'rgba(255,255,255,0.95)' : 'rgba(12,14,20,0.95)');
        map.setPaintProperty(l.id, 'text-halo-width', 2);
        map.setPaintProperty(l.id, 'text-halo-blur', 0.5);
        map.setPaintProperty(l.id, 'text-color', light ? '#1d2230' : '#eef1f6');
      } catch { /* some layers use data-driven colours; leave those as they are */ }
    });
    setLabelLayer(symbols[0] ? symbols[0].id : '');
  }, [theme]);

  // until the style is loaded we don't know where the labels start; draw nothing rather than over them
  const opacity = fade(zoom);
  const placed = labelLayer === null ? [] : [...layers.filter(Boolean).map((l) => l.clone({ opacity })), outline]
    .filter(Boolean).map((l) => (labelLayer ? l.clone({ beforeId: labelLayer }) : l));

  return (
    <Map key={style} initialViewState={initialViewState} mapStyle={style} onLoad={onLoad} onMove={onMove}
      style={{ width: '100%', height: '100%' }}>
      <DeckOverlay interleaved layers={placed} getTooltip={getTooltip} />
    </Map>
  );
}
