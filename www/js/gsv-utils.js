/**
 * gsv-utils.js
 * Shared utilities for the GSV City Explorer.
 *
 * Provides the data-host base URL, the provider registry (GSV/Mapillary),
 * the YlOrRd color scale, filename→provider detection, gzip JSON fetching,
 * and the aggregate-record adapter — used by both the overview map
 * (index.js) and the per-city detail view (city.js).
 *
 * @module gsv-utils
 */

/** Base URL for all GSV tracker data files. */
const GSV_DATA_BASE_URL =
  "https://makeabilitylab.cs.washington.edu/public/gsv-tracker/data/";

/**
 * Imagery provider registry. Each provider's color scale is anchored to
 * its launch date (oldest possible imagery = dark red), and each supplies
 * its own pano viewer deep-link and required attribution.
 */
const PROVIDERS = {
  gsv: {
    label: "Google Street View",
    panoNoun: "Google Panoramas",
    launchDate: new Date("2007-05-25"),
    attribution: "Panorama metadata © Google",
    viewerLabel: "View in Google Street View",
    viewerUrl: (panoId) =>
      `https://www.google.com/maps/@?api=1&map_action=pano&pano=${encodeURIComponent(panoId)}`,
  },
  mapillary: {
    label: "Mapillary",
    panoNoun: "Mapillary Panoramas",
    launchDate: new Date("2014-01-01"),
    attribution:
      'Image metadata © <a href="https://www.mapillary.com">Mapillary</a>, CC BY-SA',
    viewerLabel: "View in Mapillary",
    viewerUrl: (panoId) =>
      `https://www.mapillary.com/app/?pKey=${encodeURIComponent(panoId)}`,
  },
};

const MS_PER_YEAR = 1000 * 60 * 60 * 24 * 365.25;

/**
 * Maximum age (in years) mapped to the dark-red end of the color scale,
 * per provider. Computed once at load time so scales stay stable within
 * a session.
 */
const MAX_COLOR_AGE_BY_PROVIDER = Object.fromEntries(
  Object.entries(PROVIDERS).map(([key, p]) =>
    [key, (Date.now() - p.launchDate.getTime()) / MS_PER_YEAR])
);

/** Back-compat alias (GSV scale), referenced by older code/comments. */
const MAX_COLOR_AGE_IN_YEARS = MAX_COLOR_AGE_BY_PROVIDER.gsv;

/**
 * Return a CSS `rgb()` color for a given panorama age using a
 * three-stop YlOrRd interpolation (light yellow → orange → dark red),
 * scaled to the provider's imagery-age range.
 *
 * Stop 0 (age = 0):              rgb(255, 255, 178)  — light yellow
 * Stop 1 (age = max / 2):        rgb(253, 141,  60)  — orange
 * Stop 2 (age = provider max):   rgb(189,   0,  38)  — dark red
 *
 * @param {number} age - Panorama age in years (≥ 0).
 * @param {string} [provider="gsv"] - Provider key (see PROVIDERS).
 * @returns {string} CSS color string, e.g. `"rgb(253, 141, 60)"`.
 *
 * @example
 *   getColor(0);                 // "rgb(255, 255, 178)" — newest
 *   getColor(11, "mapillary");   // dark red — oldest possible Mapillary
 */
function getColor(age, provider = "gsv") {
  const maxAge = MAX_COLOR_AGE_BY_PROVIDER[provider] ?? MAX_COLOR_AGE_IN_YEARS;
  const ratio = Math.min(age / maxAge, 1);

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
 * Derive the imagery provider from a run data filename (the JS mirror of
 * naming.py: an optional alphabetic token between the step size and the
 * run date; no token means GSV).
 *
 * @param {string} filename - e.g. "bend--or_width_5000_height_5000_step_20_mapillary_2026-07-05.csv.gz"
 * @returns {string} Provider key ("gsv" when no token present).
 */
function getProviderFromFilename(filename) {
  const m = /_step_\d+(?:\.\d+)?_([a-z]+)_\d{4}-\d{2}-\d{2}/.exec(filename || "");
  return m && PROVIDERS[m[1]] ? m[1] : "gsv";
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
 * Flatten one aggregate city record into the flat shape the UI consumes.
 *
 * Handles all three aggregate generations:
 *   v1: already flat — passes through (gsv only)
 *   v2: {city_id, city, latest, runs, change}       (gsv only)
 *   v3: {city_id, city, providers: {gsv: {...}, mapillary: {...}}}
 *
 * Besides the historical flat fields, the result carries normalized
 * provider-agnostic keys the UI should prefer:
 *   provider        — the provider key this record was adapted for
 *   pano_count      — unique provider panos (google subset for gsv)
 *   pano_age_stats  — age stats of those panos
 *   capture_year_histogram — their year histogram ({counts} shape)
 *
 * @param {Object} rec - One entry of cities.json.gz `cities[]`.
 * @param {string} [provider="gsv"] - Which provider's view to adapt.
 * @returns {?Object} Flat record, or null when the city has no runs for
 *   the requested provider.
 */
function adaptCityRecord(rec, provider = "gsv") {
  if (!rec.latest && !rec.providers) {
    // schema v1: already flat, gsv-only
    return provider === "gsv" ? rec : null;
  }

  // v3 groups by provider; v2 is equivalent to a gsv-only providers map
  const block = rec.providers
    ? rec.providers[provider]
    : (provider === "gsv"
        ? { latest: rec.latest, runs: rec.runs, change: rec.change }
        : null);
  if (!block?.latest) return null;

  const latest = block.latest;
  const isGsv = provider === "gsv";
  const counts = latest.panorama_counts || {};
  const histograms = latest.histogram_of_capture_dates_by_year || {};

  return {
    provider,
    city_id: rec.city_id,
    city: rec.city.name,
    state: rec.city.state,
    country: rec.city.country,
    center: rec.city.center,
    bounds: rec.city.bounds,
    data_file: latest.data_file,
    json_file: latest.json_file,
    search_area_km2: latest.search_area_km2,
    coverage_rate_percent: latest.coverage_rate_percent,
    panorama_counts: counts,
    all_panos_age_stats: latest.all_panos_age_stats,
    google_panos_age_stats: latest.google_panos_age_stats,
    collection_info: latest.collection_info,
    histogram_of_capture_dates_by_year: histograms,
    latest_run_date: latest.run_date,
    runs: block.runs || [],
    change: block.change || null,
    // False for archival GSV runs that never captured copyright_info
    // (their Google subset is unknown; the fallbacks below kick in)
    copyright_info_available: latest.copyright_info_available ?? true,
    // Normalized provider-agnostic fields (prefer these in UI code)
    pano_count: isGsv ? (counts.unique_google_panos ?? counts.unique_panos)
                      : counts.unique_panos,
    pano_age_stats: isGsv ? (latest.google_panos_age_stats ?? latest.all_panos_age_stats)
                          : latest.all_panos_age_stats,
    capture_year_histogram: isGsv ? (histograms.google_panos ?? histograms.all_panos)
                                  : histograms.all_panos,
  };
}

/**
 * Adapt a whole cities.json.gz payload (v1, v2, or v3) to the flat-record
 * shape for one provider, returning {meta, cities}. Cities with no runs
 * for the provider are omitted.
 *
 * @param {Object} data - Parsed cities.json.gz payload.
 * @param {string} [provider="gsv"] - Which provider's view to adapt.
 * @returns {{meta: Object, cities: Object[]}}
 */
function adaptCitiesPayload(data, provider = "gsv") {
  if (!data?.cities || !Array.isArray(data.cities)) {
    throw new Error("Invalid data format: missing cities array");
  }
  return {
    meta: {
      citiesCount: data.cities_count,
      generatedAt: data.generated_at || data.creation_timestamp,
      schemaVersion: data.schema_version || 1,
    },
    cities: data.cities
      .map((rec) => adaptCityRecord(rec, provider))
      .filter(Boolean),
  };
}
