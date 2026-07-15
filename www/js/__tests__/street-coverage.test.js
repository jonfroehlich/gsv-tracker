// Offline unit tests for the pure helpers in street-coverage.js (issue #24).
// Run with `npm test` (Node's built-in test runner) — no network, no jsdom.
// In the browser these helpers read shared globals from streetscape-utils.js;
// here we stub just the two they touch (STREETSCAPE_DATA_BASE_URL, getColor).

const test = require("node:test");
const assert = require("node:assert/strict");

global.STREETSCAPE_DATA_BASE_URL = "https://example.test/data/";
global.getColor = (age, provider) => `color(${age},${provider})`;

const {
  streetsUrlForDataFile,
  styleStreetFeature,
  STREET_UNCOVERED_COLOR,
  STREET_COVERED_NODATE_COLOR,
} = require("../street-coverage.js");

test("streetsUrlForDataFile swaps .csv.gz for _streets.json.gz under the data base URL", () => {
  // Mirrors naming.streets_filename_for_run on the Python side — keep in sync.
  assert.equal(
    streetsUrlForDataFile("bend--or_width_5000_height_5000_step_20_2026-07-08.csv.gz"),
    "https://example.test/data/bend--or_width_5000_height_5000_step_20_2026-07-08_streets.json.gz"
  );
  // Provider-tagged run filenames keep their token.
  assert.equal(
    streetsUrlForDataFile("bend--or_width_5000_height_5000_step_20_mapillary_2026-07-08.csv.gz"),
    "https://example.test/data/bend--or_width_5000_height_5000_step_20_mapillary_2026-07-08_streets.json.gz"
  );
});

test("styleStreetFeature: uncovered segments are gray and dashed", () => {
  const style = styleStreetFeature({ properties: { covered: false } }, "gsv");
  assert.equal(style.color, STREET_UNCOVERED_COLOR);
  assert.equal(style.dashArray, "4 4");
});

test("styleStreetFeature: covered segment without a date uses the fallback color", () => {
  const style = styleStreetFeature(
    { properties: { covered: true, nearest_pano_age_years: null } },
    "gsv"
  );
  assert.equal(style.color, STREET_COVERED_NODATE_COLOR);
  assert.equal(style.dashArray, undefined);
});

test("styleStreetFeature: covered segment with an age uses the provider age scale", () => {
  const style = styleStreetFeature(
    { properties: { covered: true, nearest_pano_age_years: 3.2 } },
    "mapillary"
  );
  assert.equal(style.color, "color(3.2,mapillary)");
});
