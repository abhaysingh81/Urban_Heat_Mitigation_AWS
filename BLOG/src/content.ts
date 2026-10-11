// Editorial content that is not a computed number: sources, AWS roles, references.
// Computed figures live in src/data/real (exported from the repo) and are read via lib/data.ts.

export const REPO_URL = 'https://github.com/abhaysingh81/Urban_Heat_Mitigation_AWS';

/**
 * Deployment state of the SAM stack. Keep this honest: the blog's AWS chapter changes its wording on it.
 * 'templated' = template validated (cfn-lint), not yet deployed. 'deployed' = stack live in a region.
 */
export const AWS_STATUS: 'templated' | 'deployed' = 'templated';

export const SOURCES = [
  { name: 'Landsat 8/9 Collection 2 Level-2', what: 'Surface temperature: the target the model learns', res: '30 m → 500 m', licence: 'Public domain, USGS' },
  { name: 'Sentinel-2 L2A', what: 'NDVI (green), NDBI (built-up), MNDWI (water)', res: '10–20 m', licence: 'Copernicus, free and open' },
  { name: 'ESA WorldCover 2021', what: 'Share of trees, built-up, bare soil, water', res: '10 m', licence: 'CC BY 4.0' },
  { name: 'Copernicus DEM GLO-30', what: 'Elevation and slope', res: '30 m', licence: 'Copernicus licence' },
  { name: 'Meta HRSL population', what: 'People per cell, from the AWS Open Data Registry', res: '30 m', licence: 'CC BY 4.0' },
  { name: 'OpenStreetMap', what: 'City boundary, hospitals, drinking water, bus stops', res: 'vector', licence: 'ODbL 1.0' },
  { name: 'Open-Meteo (ERA5)', what: 'Scene-day weather, heat index, wet-bulb; daily forecast', res: 'city', licence: 'CC BY 4.0' },
];

export const LOOP = [
  { verb: 'Observe', text: 'Landsat surface temperature and land-cover features on a 500 m grid.' },
  { verb: 'Rank', text: 'Hazard × exposure × vulnerability, per ward, every component visible.' },
  { verb: 'Compare', text: 'Five cooling actions with published low/mid/high effect ranges.' },
  { verb: 'Allocate', text: 'A fixed budget, with a dial between cooling per rupee and equity.' },
  { verb: 'Explain', text: 'A ward brief in Hindi and English whose numbers are machine-checked.' },
  { verb: 'Alert', text: 'A 06:00 forecast job that re-ranks wards and sends the day’s alert.' },
];

export type AwsNode = { id: string; name: string; job: string };

export const AWS_SERVICES: AwsNode[] = [
  { id: 'scheduler', name: 'EventBridge Scheduler', job: 'Fires the forecast job at 06:00 IST every day.' },
  { id: 'refresh', name: 'Lambda · forecast job', job: 'Pulls the forecast, re-ranks wards for today, writes the result to S3, decides the alert level.' },
  { id: 'sns', name: 'SNS', job: 'Emails the day’s heat alert when the level crosses the threshold.' },
  { id: 'polly', name: 'Polly', job: 'Reads the advisory aloud in Hindi (neural voice Kajal) for people who will not read an email.' },
  { id: 's3', name: 'S3', job: 'Processed grids, the model, today’s risk, PDF briefs and audio advisories.' },
  { id: 'cloudfront', name: 'CloudFront', job: 'Serves the officer and citizen web app from a private S3 bucket (origin access control).' },
  { id: 'apigw', name: 'API Gateway (HTTP API)', job: 'One throttled entry point for risk, plans, briefs, reports and the model card.' },
  { id: 'api', name: 'Lambda · FastAPI', job: 'The decision engine: risk, optimizer, scenarios, exports. A 2 GB container image.' },
  { id: 'bedrock', name: 'Bedrock + Guardrails', job: 'Writes the ward brief through a Strands agent; the guardrail filters topics and content.' },
  { id: 'dynamo', name: 'DynamoDB', job: 'Plans with an audit trail (draft → approved → implemented) and citizen reports.' },
  { id: 'cloudwatch', name: 'CloudWatch + Budgets', job: 'Dashboard, alarms on API errors and failed refreshes, and a monthly spend cap.' },
];

/** two request paths through the stack, as ordered node ids */
export const AWS_PATHS = {
  morning: ['scheduler', 'refresh', 's3', 'sns', 'polly'],
  officer: ['cloudfront', 'apigw', 'api', 'bedrock', 'dynamo', 's3'],
} as const;

export const SHAP_LABEL: Record<string, string> = {
  ndbi_mean: 'Built-up index (NDBI)',
  air_temp_max: 'Air temperature on scene days',
  frac_water: 'Share of water',
  mndwi_mean: 'Water index (MNDWI)',
  elev_mean: 'Elevation',
  ndvi_mean_ctx7: 'Greenness of the surrounding 3.5 km',
  ndvi_mean: 'Greenness (NDVI)',
  humidity_mean: 'Humidity on scene days',
  frac_tree: 'Share of tree cover',
  ndvi_mean_ctx3: 'Greenness of the surrounding 1.5 km',
};

export const REFERENCES = [
  { text: 'World Health Organization. Heat and health, fact sheet.', url: 'https://www.who.int/news-room/fact-sheets/detail/climate-change-heat-and-health' },
  { text: 'Romanello, M. et al. The 2024 report of the Lancet Countdown on health and climate change.', url: 'https://discovery.ucl.ac.uk/id/eprint/10200213/' },
  { text: 'Pillai, A. V. and Dalal, T. How is India adapting to heatwaves? An assessment of heat action plans. Centre for Policy Research, 2023.', url: 'https://ghhin.org/resources/how-is-india-adapting-to-heatwaves-an-assessment-of-heat-action-plans-with-insights-for-transformative-climate-action/' },
  { text: 'USGS. Landsat Collection 2 Surface Temperature.', url: 'https://www.usgs.gov/landsat-missions/landsat-collection-2-surface-temperature' },
  { text: 'US EPA. Reducing Urban Heat Islands: Compendium of Strategies.', url: 'https://www.epa.gov/heatislands/heat-island-compendium' },
  { text: 'Strands Agents, open-source agent SDK from AWS.', url: 'https://strandsagents.com' },
];

export const AI_TOOLS = [
  'Claude Code (Anthropic) helped write the data pipeline, model training, API, infrastructure template and this page.',
  'Google AI Studio (Gemini) produced the first draft of this page, which we rewrote.',
];
