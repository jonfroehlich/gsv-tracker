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
  styleStreetByCoverage,
  styleStreetByType,
  styleForMode,
  streetTypeColor,
  streetTypeOrder,
  withStreetAlpha,
  STREET_UNCOVERED_COLOR,
  STREET_COVERED_COLOR,
  STREET_COVERED_NODATE_COLOR,
  STREET_TYPE_MINOR_COLOR,
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

test("streetsUrlForDataFile throws on a non-.csv.gz filename (mirrors the Python contract)", () => {
  // Without the suffix guard the regex replace is a no-op and we'd fetch the
  // wrong URL; match naming.streets_filename_for_run and throw instead.
  assert.throws(() => streetsUrlForDataFile("bend--or_streets.json.gz"), /Not a run csv\.gz/);
  assert.throws(() => streetsUrlForDataFile("bend--or.csv"), /Not a run csv\.gz/);
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

test("styleStreetByCoverage: binary covered green vs uncovered slate (dashed)", () => {
  assert.equal(
    styleStreetByCoverage({ properties: { covered: true } }).color,
    STREET_COVERED_COLOR
  );
  const uncovered = styleStreetByCoverage({ properties: { covered: false } });
  assert.equal(uncovered.color, STREET_UNCOVERED_COLOR);
  assert.equal(uncovered.dashArray, "4 4");
});

test("styleStreetByType: colors by highway class; uncovered is faded + dashed", () => {
  const covered = styleStreetByType({ properties: { covered: true, highway: "residential" } });
  assert.equal(covered.color, streetTypeColor("residential"));
  assert.equal(covered.dashArray, undefined);

  const uncovered = styleStreetByType({ properties: { covered: false, highway: "residential" } });
  assert.equal(uncovered.color, streetTypeColor("residential")); // keeps its type hue
  assert.equal(uncovered.dashArray, "4 4");
  assert.ok(uncovered.opacity < covered.opacity); // but faded
});

test("streetTypeColor: unlisted classes fold into the neutral minor color", () => {
  assert.equal(streetTypeColor("motorway"), "#3987e5");
  assert.equal(streetTypeColor("living_street"), STREET_TYPE_MINOR_COLOR);
  assert.equal(streetTypeColor("other"), STREET_TYPE_MINOR_COLOR);
});

test("streetTypeOrder: importance rank, unlisted classes sort last", () => {
  assert.ok(streetTypeOrder("motorway") < streetTypeOrder("residential"));
  assert.ok(streetTypeOrder("residential") < streetTypeOrder("other"));
});

test("styleForMode: dispatches to the right per-mode styler", () => {
  const feat = { properties: { covered: true, highway: "primary", nearest_pano_age_years: 1 } };
  assert.equal(styleForMode(feat, "coverage", "gsv").color, STREET_COVERED_COLOR);
  assert.equal(styleForMode(feat, "type", "gsv").color, streetTypeColor("primary"));
  assert.equal(styleForMode(feat, "age", "gsv").color, "color(1,gsv)"); // stubbed getColor
});

test("withStreetAlpha: hex to rgba() with the given alpha", () => {
  assert.equal(withStreetAlpha("#2fb974", 0.22), "rgba(47, 185, 116, 0.22)");
});
