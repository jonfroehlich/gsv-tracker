/**
 * gsv-utils.js
 * Shared utilities for the GSV City Explorer.
 *
 * Provides the data-host base URL, YlOrRd color scale, and a helper
 * for fetching gzip-compressed JSON — used by both the overview map
 * (index.js) and the per-city detail view (city.js).
 *
 * @module gsv-utils
 */

/** Base URL for all GSV tracker data files. */
const GSV_DATA_BASE_URL =
  "https://makeabilitylab.cs.washington.edu/public/gsv-tracker/data/";

/** Google Street View public launch date. */
const GSV_LAUNCH_DATE = new Date("2007-05-25");

/**
 * Maximum age (in years) mapped to the dark-red end of the color scale.
 * Computed once at load time so the scale stays stable within a session.
 */
const MAX_COLOR_AGE_IN_YEARS =
  (Date.now() - GSV_LAUNCH_DATE.getTime()) / (1000 * 60 * 60 * 24 * 365.25);

/**
 * Return a CSS `rgb()` color for a given panorama age using a
 * three-stop YlOrRd interpolation (light yellow → orange → dark red).
 *
 * Stop 0 (age = 0):                    rgb(255, 255, 178)  — light yellow
 * Stop 1 (age = MAX_COLOR_AGE / 2):    rgb(253, 141,  60)  — orange
 * Stop 2 (age = MAX_COLOR_AGE_IN_YEARS): rgb(189,   0,  38) — dark red
 *
 * @param {number} age - Panorama age in years (≥ 0).
 * @returns {string} CSS color string, e.g. `"rgb(253, 141, 60)"`.
 *
 * @example
 *   getColor(0);                        // "rgb(255, 255, 178)" — newest
 *   getColor(MAX_COLOR_AGE_IN_YEARS);   // "rgb(189, 0, 38)"   — oldest
 */
function getColor(age) {
  const ratio = Math.min(age / MAX_COLOR_AGE_IN_YEARS, 1);

  let r, g, b;
  if (ratio < 0.5) {
    const t = ratio * 2;
    r = 255 - t * (255 - 253);
    g = 255 - t * (255 - 141);
    b = 178 - t * (178 - 60);
  } else {
    const t = (ratio - 0.5) * 2;
    r = 253 - t * (253 - 189);
    g = 141 - t * 141;
    b = 60  - t * (60  - 38);
  }
  return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
}

/**
 * Fetch a `.json.gz` file, decompress it with pako, and return the
 * parsed object.
 *
 * Note: pako is used here (rather than the native DecompressionStream)
 * because this function loads small metadata JSON files where the full
 * response is collected before parsing — the streaming pipeline in
 * city.js uses DecompressionStream for the large CSV files.
 *
 * @param {string} url - Full URL to the `.json.gz` resource.
 * @returns {Promise<Object>} The parsed JSON payload.
 * @throws {Error} On HTTP error or decompression/parse failure.
 *
 * @example
 *   const cities = await fetchGzippedJson(GSV_DATA_BASE_URL + "cities.json.gz");
 */
async function fetchGzippedJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status} fetching ${url}`);
  }
  const compressed = await response.arrayBuffer();
  const text = pako.inflate(new Uint8Array(compressed), { to: "string" });
  return JSON.parse(text);
}

/**
 * Flatten a schema-v2 aggregate city record into the flat shape the UI
 * code consumes (v1 records pass through unchanged).
 *
 * v2 groups per-city data as {city_id, city: {...}, latest: {...},
 * runs: [...], change}; the UI historically read everything off the top
 * level, so this adapter keeps those call sites tiny.
 *
 * @param {Object} rec - One entry of cities.json.gz `cities[]`.
 * @returns {Object} Flat record with `city` (name string), `state`,
 *   `country`, `bounds`, stats fields, plus v2 extras `city_id`,
 *   `latest_run_date`, `runs`, and `change` when present.
 */
function adaptCityRecord(rec) {
  if (!rec.latest) return rec; // schema v1: already flat

  return {
    city_id: rec.city_id,
    city: rec.city.name,
    state: rec.city.state,
    country: rec.city.country,
    center: rec.city.center,
    bounds: rec.city.bounds,
    data_file: rec.latest.data_file,
    json_file: rec.latest.json_file,
    search_area_km2: rec.latest.search_area_km2,
    coverage_rate_percent: rec.latest.coverage_rate_percent,
    panorama_counts: rec.latest.panorama_counts,
    all_panos_age_stats: rec.latest.all_panos_age_stats,
    google_panos_age_stats: rec.latest.google_panos_age_stats,
    collection_info: rec.latest.collection_info,
    histogram_of_capture_dates_by_year: rec.latest.histogram_of_capture_dates_by_year,
    latest_run_date: rec.latest.run_date,
    runs: rec.runs || [],
    change: rec.change || null,
  };
}

/**
 * Adapt a whole cities.json.gz payload (v1 or v2) to the flat-record
 * shape, returning {meta, cities}.
 *
 * @param {Object} data - Parsed cities.json.gz payload.
 * @returns {{meta: Object, cities: Object[]}}
 */
function adaptCitiesPayload(data) {
  if (!data?.cities || !Array.isArray(data.cities)) {
    throw new Error("Invalid data format: missing cities array");
  }
  return {
    meta: {
      citiesCount: data.cities_count,
      generatedAt: data.generated_at || data.creation_timestamp,
      schemaVersion: data.schema_version || 1,
    },
    cities: data.cities.map(adaptCityRecord),
  };
}