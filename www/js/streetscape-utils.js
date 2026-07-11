/**
 * streetscape-utils.js
 * Shared utilities for the Streetscape City Explorer.
 *
 * Provides the data-host base URL, the provider registry (GSV/Mapillary),
 * the YlOrRd color scale, filename→provider detection, gzip JSON fetching,
 * and the aggregate-record adapter — used by both the overview map
 * (index.js) and the per-city detail view (city.js).
 *
 * @module streetscape-utils
 */

/** Base URL for all Streetscape Tracker data files. */
const STREETSCAPE_DATA_BASE_URL =
  "https://makeabilitylab.cs.washington.edu/public/streetscape-tracker/data/";

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
 * True iff `key` is a real provider key ("gsv"/"mapillary").
 *
 * Uses Object.hasOwn rather than a truthy `PROVIDERS[key]` lookup so
 * attacker-controlled strings that name Object.prototype members
 * (?provider=constructor) can never pass as a provider.
 *
 * @param {*} key - Candidate provider key (e.g. from a URL parameter).
 * @returns {boolean}
 */
function isKnownProvider(key) {
  return typeof key === "string" && Object.hasOwn(PROVIDERS, key);
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
  return m && isKnownProvider(m[1]) ? m[1] : "gsv";
}

/**
 * HTML-escape a string for safe interpolation into an HTML template.
 *
 * Every data-derived string that enters innerHTML / bindPopup /
 * bindTooltip markup MUST pass through this: copyright/photographer
 * fields are arbitrary third-party content (Mapillary contributor names,
 * archival GSV photographer credits), and city/state/country names come
 * from publicly editable OSM/Nominatim data.
 *
 * @param {*} value - Any value; non-strings are stringified ("" for null/undefined).
 * @returns {string} The escaped string.
 */
function escapeHtml(value) {
  if (value == null) return "";
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

/**
 * Validate a run-data filename from an untrusted source (the ?file= URL
 * parameter) against the filename contract (the JS mirror of naming.py).
 *
 * Accepts every run-filename generation — legacy undated, buggy float
 * step, dated, provider-tagged — and rejects anything else, in particular
 * path separators / traversal, so a crafted ?file= can never fetch
 * resources outside the published data directory or non-run artifacts.
 *
 * @param {?string} filename - Candidate filename (no directories).
 * @returns {boolean} True iff it looks like a published run csv.gz.
 */
function isValidRunFilename(filename) {
  if (typeof filename !== "string") return false;
  return /^[^/\\?#]+_width_\d+_height_\d+_step_\d+(?:\.\d+)?(?:_[a-z]+)?(?:_\d{4}-\d{2}-\d{2})?\.csv\.gz$/
    .test(filename);
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
 *   const cities = await fetchGzippedJson(STREETSCAPE_DATA_BASE_URL + "cities.json.gz");
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
    // schema v1: flat, gsv-only. A raw v1 record has the historical flat
    // fields but NOT the normalized keys (provider/pano_count/
    // pano_age_stats/capture_year_histogram), so derive them here rather
    // than passing the record through untouched — consumers read
    // pano_age_stats.median_pano_age_years unconditionally.
    if (provider !== "gsv") return null;
    const v1Counts = rec.panorama_counts || {};
    const v1Histograms = rec.histogram_of_capture_dates_by_year || {};
    return {
      ...rec,
      provider: "gsv",
      city_id: rec.city_id ?? null,
      runs: rec.runs || [],
      change: rec.change || null,
      latest_run_date: rec.latest_run_date ?? null,
      copyright_info_available: rec.copyright_info_available ?? true,
      pano_count: v1Counts.unique_google_panos ?? v1Counts.unique_panos,
      pano_age_stats: rec.google_panos_age_stats ?? rec.all_panos_age_stats,
      capture_year_histogram: v1Histograms.google_panos ?? v1Histograms.all_panos,
    };
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

// ---------------------------------------------------------------------------
// Pure display/derivation helpers.
//
// These carry the numeric/date edge cases that produced the B1–B4 tooltip
// bugs (Infinity%/NaN) and the 0-pano epoch-date bug (#122/#69). They are
// deliberately DOM-free and side-effect-free so index.js/city.js can share
// them and the Node unit tests (issue #123) can exercise them directly.
// ---------------------------------------------------------------------------

/**
 * Exact "official Google" copyright test — the JS mirror of
 * analysis.is_google_copyright. Matches ONLY the literal `© Google`
 * string, never a substring, because third-party photographer names can
 * themselves contain "Google" (e.g. "Google Street View contributor").
 *
 * @param {?string} copyright - A run row's copyright_info field.
 * @returns {boolean} True iff the imagery is official Google.
 */
function isGoogleCopyright(copyright) {
  return copyright === "© Google";
}

/**
 * Parse a pano capture date, returning null when the date is absent
 * (age_stats are all null for a 0-pano run). Guards against
 * `new Date(null)` silently rendering as the Unix epoch (12/31/1969)
 * instead of a "—"/"No data" placeholder (issue #122, #69 family).
 *
 * Date-ONLY strings ("YYYY-MM-DD") are parsed as LOCAL midnight, not UTC:
 * `new Date("2023-01-01")` is UTC midnight, and reading it back with local
 * getters (toLocaleDateString, getFullYear) west of UTC shifts every date
 * back a day — and every January/year-precision capture date back a whole
 * YEAR (standardize_capture_date pins month/year precision to the 1st), so
 * US visitors saw those panos in the previous year's filter bucket and
 * color. Full timestamps (with a time component) still parse natively.
 *
 * @param {?string} v - ISO date string, or null/undefined.
 * @returns {?Date} A Date (local midnight for date-only), or null when falsy.
 */
function panoDateOrNull(v) {
  if (!v) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(v));
  if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  return new Date(v);
}

/**
 * Official-Google share of all found panoramas, as a fixed-1-decimal
 * percent string. Guards the divide-by-zero on a 0-pano run that would
 * otherwise render "Infinity%" in the overview tooltip (B1–B4 audit).
 *
 * @param {number} googleCount - Unique official-Google panos.
 * @param {number} totalCount - Unique panos of all copyrights.
 * @returns {string} e.g. "37.2"; "0.0" when totalCount <= 0.
 */
function googleSharePercent(googleCount, totalCount) {
  if (!(totalCount > 0)) return "0.0";
  return ((googleCount / totalCount) * 100).toFixed(1);
}

/**
 * Build a gap-filled year→count histogram from a sparse capture-year map,
 * spanning the earliest present year through currentYear (inclusive), with
 * missing interior years zero-filled. Returns {} when there are no years,
 * avoiding the `Math.min(...[]) === Infinity` blow-up on an empty or
 * missing histogram (issue #69).
 *
 * @param {?Object<string|number, number>} rawHistogram - Sparse year→count.
 * @param {number} currentYear - Upper bound (inclusive) of the fill range.
 * @returns {Object<number, number>} Dense year→count, or {} when empty.
 */
function buildFilledHistogram(rawHistogram, currentYear) {
  const source = rawHistogram || {};
  const years = Object.keys(source).map(Number);
  const filled = {};
  if (years.length > 0) {
    const startYear = Math.min(...years);
    for (let y = startYear; y <= currentYear; y++) {
      filled[y] = source[y] || 0;
    }
  }
  return filled;
}

// Node/CommonJS export shim for the unit tests (issue #123). This is a no-op
// in the browser, where these symbols are plain globals loaded via <script>.
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    STREETSCAPE_DATA_BASE_URL,
    PROVIDERS,
    isKnownProvider,
    getColor,
    escapeHtml,
    isValidRunFilename,
    getProviderFromFilename,
    fetchGzippedJson,
    adaptCityRecord,
    adaptCitiesPayload,
    isGoogleCopyright,
    panoDateOrNull,
    googleSharePercent,
    buildFilledHistogram,
  };
}
