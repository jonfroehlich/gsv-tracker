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

/** Maximum age (in years) mapped to the dark-red end of the scale. */
const MAX_COLOR_AGE_IN_YEARS =
  (Date.now() - GSV_LAUNCH_DATE.getTime()) / (1000 * 60 * 60 * 24 * 365.25);

/**
 * Return a CSS `rgb()` color for a given panorama age using a
 * three-stop YlOrRd interpolation (light yellow → orange → dark red).
 *
 * @param {number} age - Panorama age in years.
 * @returns {string} CSS color value, e.g. `"rgb(253, 141, 60)"`.
 *
 * @example
 *   getColor(0);                      // yellow (newest)
 *   getColor(MAX_COLOR_AGE_IN_YEARS);  // dark red (oldest)
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
    b = 60 - t * (60 - 38);
  }
  return `rgb(${Math.round(r)}, ${Math.round(g)}, ${Math.round(b)})`;
}

/**
 * Fetch a `.json.gz` file, inflate it with pako, and return the
 * parsed object. Handles bare `NaN` / `Infinity` literals that
 * standard JSON cannot represent (some data files include them).
 *
 * @param {string} url - Full URL to the `.json.gz` resource.
 * @returns {Promise<Object>} The parsed JSON payload.
 * @throws {Error} On HTTP error or decompression failure.
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
  return JSON.parse(text.replace(/:\s*(NaN|-?Infinity)\b/g, ": null"));
}
