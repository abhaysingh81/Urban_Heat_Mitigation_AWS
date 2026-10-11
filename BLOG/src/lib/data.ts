// Typed access to the numbers exported from the repo by `python -m scripts.export_blog_data`.
// Nothing in the story is typed by hand: re-run the export and the blog follows.

import { useEffect, useState } from 'react';
import modelJson from '../data/real/model.json';
import wardsJson from '../data/real/wards.json';
import plansJson from '../data/real/plans.json';
import sitesJson from '../data/real/sites.json';
import briefJson from '../data/real/brief.json';

export const CITY_IDS = ['new_delhi', 'mumbai', 'jaipur', 'bengaluru'] as const;
export type CityId = (typeof CITY_IDS)[number];

export const CITY_NAME: Record<CityId, string> = {
  new_delhi: 'Delhi',
  mumbai: 'Mumbai',
  jaipur: 'Jaipur',
  bengaluru: 'Bengaluru',
};

export interface Grid {
  city: CityId;
  name: string;
  rows: number;
  cols: number;
  cells: number;
  wards: number;
  lst: (number | null)[];
  ndvi: (number | null)[];
  imperv: (number | null)[];
  pop: (number | null)[];
  lst_stats: { min: number; max: number; mean: number; p5: number; p95: number };
}

export interface Ward {
  ward_id: string;
  ward_name: string;
  rank: number;
  risk_score: number;
  hazard: number;
  exposure: number;
  vulnerability: number;
  population: number;
  lst_mean: number;
}

export interface Plan {
  budget_lakh: number;
  equity_weight: number;
  people_protected: number;
  n_actions: number;
  spent_lakh: number;
  cooling_c: { low: number; mid: number; high: number };
  cost_per_person_inr: number;
  high_vuln_share: number;
  by_type: { label: string; count: number; cost_lakh: number }[];
}

/** [gridIndex, isCoolingCentre (0|1), people] */
export type Site = [number, number, number];

export const model = modelJson as unknown as {
  version: string;
  variant: string;
  n_cells: number;
  n_features: number;
  target: string;
  loco: Record<CityId, { n: number; pearson_r: number; rmse: number; bias: number; r2: number }>;
  baseline_r: Record<CityId, number>;
  block_cv: Record<CityId, { pearson_r: number; rmse: number }>;
  coverage_raw: Record<CityId, number>;
  coverage_calibrated: Record<CityId, number>;
  band_widen_c: number;
  shap: { feature: string; mean_abs_shap: number }[];
  limitations: string[];
};

export const wards = wardsJson as unknown as Record<CityId, { of_wards: number; top: Ward[] }>;
export const plans = plansJson as unknown as Record<CityId, Plan[]>;
export const sites = sitesJson as unknown as Record<CityId, { budget_lakh: number; '0.0': Site[]; '1.0': Site[] }>;
export const brief = briefJson as { ward_id: string; forecast_note: string; en: string; hi: string };

const loaders: Record<CityId, () => Promise<{ default: unknown }>> = {
  new_delhi: () => import('../data/real/grid_new_delhi.json'),
  mumbai: () => import('../data/real/grid_mumbai.json'),
  jaipur: () => import('../data/real/grid_jaipur.json'),
  bengaluru: () => import('../data/real/grid_bengaluru.json'),
};

const cache = new Map<CityId, Promise<Grid>>();

export function loadGrid(id: CityId): Promise<Grid> {
  if (!cache.has(id)) cache.set(id, loaders[id]().then((m) => m.default as Grid));
  return cache.get(id)!;
}

export function useGrid(id: CityId): Grid | null {
  const [grid, setGrid] = useState<Grid | null>(null);
  useEffect(() => {
    let live = true;
    loadGrid(id).then((g) => live && setGrid(g));
    return () => {
      live = false;
    };
  }, [id]);
  return grid && grid.city === id ? grid : null;
}

// Totals used in the copy, computed rather than typed.
export const totals = {
  realCells: model.n_cells,
  minR: Math.min(...CITY_IDS.map((c) => model.loco[c].pearson_r)),
  maxR: Math.max(...CITY_IDS.map((c) => model.loco[c].pearson_r)),
};
