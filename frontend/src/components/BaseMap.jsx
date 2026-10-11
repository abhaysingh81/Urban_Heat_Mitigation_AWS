import { useCallback, useMemo, useRef, useState } from 'react';
import { GeoJsonLayer } from '@deck.gl/layers';
import Map, { useControl } from 'react-map-gl/maplibre';
import { MapboxOverlay } from '@deck.gl/mapbox';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useTheme } from '../ThemeContext';
import { LOCATION_KEY, LOCATION_REGION } from '../location';

const CARTO_DARK = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';
const CARTO_LIGHT = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

const getStyleUrl = (theme, useLocation = true) => {
  // Amazon Location (optional): without a key the CARTO styles keep local dev working
  if (LOCATION_KEY && useLocation) {
    const scheme = theme === 'light' ? 'Light' : 'Dark';
    return `https://maps.geo.${LOCATION_REGION}.amazonaws.com/v2/styles/Monochrome/descriptor?key=${LOCATION_KEY}&color-scheme=${scheme}&political-view=IND`;
  }
  return theme === 'light' ? CARTO_LIGHT : CARTO_DARK;
};

function DeckOverlay(props) {
  const overlay = useControl(() => new MapboxOverlay(props));
  overlay.setProps(props);
  return null;
}

const fade = (z) => Math.max(0.35, Math.min(0.85, 0.85 - (z - 10.5) * 0.15));

// By default layers are drawn under the basemap's labels and thin out as you zoom in, so place
// names stay readable over the heat grid. Pass onTop for layers that must stay solid and above
// everything (e.g. a walking route and its markers).
export default function BaseMap({ initialViewState, layers, getTooltip, boundary, onTop = false }) {
  const { theme } = useTheme();
  const [zoom, setZoom] = useState(initialViewState?.zoom ?? 10);
  const onMove = useCallback((e) => {
    const z = Math.round(e.viewState.zoom * 4) / 4;
    setZoom((old) => (old === z ? old : z));
  }, []);
  const outline = useMemo(() => (boundary ? new GeoJsonLayer({
    id: 'city-boundary', data: boundary, filled: false, stroked: true, pickable: false,
    getLineColor: theme === 'light' ? [40, 40, 60, 220] : [235, 235, 245, 220],
    lineWidthUnits: 'pixels', getLineWidth: 2,
  }) : null), [boundary, theme]);
  
  // If the Amazon Location style cannot load (key not valid for this origin, service unreachable),
  // switch to the CARTO style instead of leaving an empty map with no data layers.
  const [locationFailed, setLocationFailed] = useState(false);
  const style = getStyleUrl(theme, !locationFailed);
  const [labelLayer, setLabelLayer] = useState(null);
  const loaded = useRef(false);
  const onError = useCallback(() => { if (!loaded.current) setLocationFailed(true); }, []);

  const onLoad = useCallback((e) => {
    const map = e.target;
    loaded.current = true;
    const symbols = map.getStyle().layers.filter((l) => l.type === 'symbol');
    const light = theme === 'light';
    symbols.filter((l) => l.layout && l.layout['text-field']).forEach((l) => {
      try {
        map.setPaintProperty(l.id, 'text-halo-color', light ? 'rgba(255,255,255,0.95)' : 'rgba(12,14,20,0.95)');
        map.setPaintProperty(l.id, 'text-halo-width', 2);
        map.setPaintProperty(l.id, 'text-halo-blur', 0.5);
        map.setPaintProperty(l.id, 'text-color', light ? '#1d2230' : '#eef1f6');
      } catch { /* a style without this paint property: leave the layer as it is */ }
    });
    setLabelLayer(symbols[0] ? symbols[0].id : '');
  }, [theme]);

  const opacity = fade(zoom);
  const placed = labelLayer === null ? [] : [...layers.filter(Boolean).map((l) => (onTop ? l : l.clone({ opacity }))), outline]
    .filter(Boolean).map((l) => (labelLayer && !onTop ? l.clone({ beforeId: labelLayer }) : l));

  return (
    <Map key={style} initialViewState={initialViewState} mapStyle={style} onLoad={onLoad} onMove={onMove}
      onError={LOCATION_KEY && !locationFailed ? onError : undefined}
      style={{ width: '100%', height: '100%' }}>
      <DeckOverlay interleaved layers={placed} getTooltip={getTooltip} />
    </Map>
  );
}
