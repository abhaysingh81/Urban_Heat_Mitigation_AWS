import { useEffect, useRef, useState } from 'react';
import type { Grid, Site } from '../lib/data';
import { GREENS, GREYS, INFERNO, LST_DOMAIN, VIOLETS, ramp } from '../lib/heat';

export type Layer = 'lst' | 'ndvi' | 'imperv' | 'pop';

export const LAYERS: Record<Layer, { label: string; legend: [string, string]; stops: typeof INFERNO; norm: (v: number) => number }> = {
  lst: {
    label: 'Surface temperature',
    legend: [`${LST_DOMAIN[0]} °C`, `${LST_DOMAIN[1]} °C`],
    stops: INFERNO,
    norm: (v) => (v - LST_DOMAIN[0]) / (LST_DOMAIN[1] - LST_DOMAIN[0]),
  },
  ndvi: { label: 'Greenness (NDVI)', legend: ['bare', 'green'], stops: GREENS, norm: (v) => (v + 0.05) / 0.6 },
  imperv: { label: 'Built-up share', legend: ['0%', '100%'], stops: GREYS, norm: (v) => v },
  pop: {
    label: 'People per km²',
    legend: ['few', '1 lakh+'],
    stops: VIOLETS,
    norm: (v) => Math.log10(v + 1) / 5,
  },
};

interface Props {
  grid: Grid;
  layer?: Layer;
  /** sweep the image in top to bottom like a satellite pass */
  reveal?: boolean;
  /** draw the base faded so overlay sites read first */
  dim?: boolean;
  sites?: Site[];
  maxHeight?: number;
  onHover?: (index: number | null) => void;
  label: string;
}

const prefersReducedMotion = () =>
  typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

export function ThermalMap({ grid, layer = 'lst', reveal = false, dim = false, sites, maxHeight, onHover, label }: Props) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0, cell: 0 });
  const [progress, setProgress] = useState(reveal && !prefersReducedMotion() ? 0 : 1);
  const hoverRef = useRef<number | null>(null);

  // fit grid to the container width, capped by maxHeight
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const width = entry.contentRect.width;
      let cell = width / grid.cols;
      if (maxHeight && cell * grid.rows > maxHeight) cell = maxHeight / grid.rows;
      setSize({ w: cell * grid.cols, h: cell * grid.rows, cell });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [grid, maxHeight]);

  // satellite-pass reveal
  useEffect(() => {
    if (!reveal || prefersReducedMotion()) {
      setProgress(1);
      return;
    }
    setProgress(0);
    let raf = 0;
    const start = performance.now();
    const dur = 1700;
    const tick = (t: number) => {
      const p = Math.min(1, (t - start) / dur);
      setProgress(1 - Math.pow(1 - p, 3));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [reveal, grid]);

  // paint
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !size.w) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.round(size.w * dpr);
    canvas.height = Math.round(size.h * dpr);
    const ctx = canvas.getContext('2d')!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);

    // native-resolution image, scaled up with crisp edges
    const src = document.createElement('canvas');
    src.width = grid.cols;
    src.height = grid.rows;
    const sctx = src.getContext('2d')!;
    const img = sctx.createImageData(grid.cols, grid.rows);
    const spec = LAYERS[layer];
    const values = grid[layer];
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      if (v == null) continue;
      const [r, g, b] = ramp(spec.stops, spec.norm(v));
      img.data[i * 4] = r;
      img.data[i * 4 + 1] = g;
      img.data[i * 4 + 2] = b;
      img.data[i * 4 + 3] = 255;
    }
    sctx.putImageData(img, 0, 0);

    const rowsShown = Math.ceil(grid.rows * progress);
    ctx.imageSmoothingEnabled = false;
    ctx.globalAlpha = dim ? 0.38 : 1;
    if (rowsShown > 0) {
      ctx.drawImage(src, 0, 0, grid.cols, rowsShown, 0, 0, size.w, rowsShown * size.cell);
    }
    ctx.globalAlpha = 1;

    if (progress < 1) {
      const y = rowsShown * size.cell;
      const grad = ctx.createLinearGradient(0, y - 24, 0, y + 2);
      grad.addColorStop(0, 'rgba(252,255,164,0)');
      grad.addColorStop(1, 'rgba(252,255,164,0.55)');
      ctx.fillStyle = grad;
      ctx.fillRect(0, Math.max(0, y - 24), size.w, 26);
    }

    if (sites && progress >= 1) {
      const rad = Math.max(2, size.cell * 0.55);
      for (const [idx, centre] of sites) {
        const x = (idx % grid.cols + 0.5) * size.cell;
        const y = (Math.floor(idx / grid.cols) + 0.5) * size.cell;
        ctx.beginPath();
        if (centre) {
          ctx.arc(x, y, rad * 1.5, 0, Math.PI * 2);
          ctx.strokeStyle = '#fcffa4';
          ctx.lineWidth = 1.5;
          ctx.stroke();
        } else {
          ctx.arc(x, y, rad, 0, Math.PI * 2);
          ctx.fillStyle = '#5ee0e6';
          ctx.fill();
        }
      }
    }
  }, [grid, layer, size, progress, dim, sites]);

  const indexAt = (e: React.PointerEvent) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const c = Math.floor(((e.clientX - rect.left) / rect.width) * grid.cols);
    const r = Math.floor(((e.clientY - rect.top) / rect.height) * grid.rows);
    if (c < 0 || r < 0 || c >= grid.cols || r >= grid.rows) return null;
    const i = r * grid.cols + c;
    return grid.lst[i] == null ? null : i;
  };

  return (
    <div ref={wrapRef} className="w-full">
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={label}
        style={{ width: size.w || '100%', height: size.h || 0, display: 'block', margin: '0 auto', touchAction: 'pan-y' }}
        onPointerMove={(e) => {
          if (!onHover) return;
          const i = indexAt(e);
          if (i !== hoverRef.current) {
            hoverRef.current = i;
            onHover(i);
          }
        }}
        onPointerLeave={() => {
          hoverRef.current = null;
          onHover?.(null);
        }}
      />
    </div>
  );
}
