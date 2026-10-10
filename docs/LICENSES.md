# Data and software licence audit

Every dataset and notable library used by the real-data tier, with its licence and the credit it requires.
Re-check before publishing; this table reflects each provider's published terms at the time of writing.

| Item | Use | Licence / terms | Credit |
|---|---|---|---|
| Landsat 8/9 Collection 2 Level-2 (USGS) via Microsoft Planetary Computer | LST target | Public domain (USGS) | "Landsat data courtesy of the U.S. Geological Survey" |
| Sentinel-2 L2A (ESA / Copernicus) via Planetary Computer | NDVI, NDBI, MNDWI | Free, full and open (Copernicus) | "Contains modified Copernicus Sentinel data" |
| ESA WorldCover 2021 | Land-cover fractions | CC BY 4.0 | © ESA WorldCover project / Contains modified Copernicus Sentinel data |
| Copernicus DEM GLO-30 | Elevation, slope | Copernicus licence (free use) | "Produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018, provided under COPERNICUS by the European Union and ESA" |
| OpenStreetMap (Overpass API) | Buildings, amenities, cooling spots | ODbL 1.0 | © OpenStreetMap contributors |
| Meta High Resolution Population Density Maps (HRSL), AWS Open Data Registry | Population | CC BY 4.0 | "Facebook/Meta Data for Good, CIESIN Columbia University" |
| Open-Meteo (ERA5-based archive and forecast API) | Weather, forecast | CC BY 4.0 (non-commercial free tier) | "Weather data by Open-Meteo.com" |
| Noto Sans / Noto Sans Devanagari fonts | Brief PDF | SIL Open Font License 1.1 | © The Noto Project Authors |
| XGBoost, scikit-learn, SHAP, pandas, FastAPI, fpdf2, Strands Agents SDK, boto3, Mangum | Software | Apache-2.0 / BSD / MIT / LGPL (fpdf2) | see each project |

Notes
- Open-Meteo's free tier is for non-commercial use; a commercial deployment needs their paid API.
- General heat-health guidance in `agent/guidance/` is paraphrased, not quoted, from public advice; it is not an official NDMA text.
- Cooling-effect ranges in `pipeline/config.py` (`REAL_INTERVENTIONS`) and cost figures are planning-grade placeholders; cite and replace with local studies/quotes before real use.
