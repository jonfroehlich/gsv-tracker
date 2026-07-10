// Offline unit tests for the pure helpers in gsv-utils.js (issue #123).
// Run with `npm test` (Node's built-in test runner) — no network, no jsdom,
// no browser. These cover the numeric/date edge cases behind the B1–B4
// tooltip bugs (Infinity%/NaN) and the 0-pano epoch-date bug (#122/#69).

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  adaptCityRecord,
  isGoogleCopyright,
  panoDateOrNull,
  googleSharePercent,
  buildFilledHistogram,
} = require("../gsv-utils.js");

// --- adaptCityRecord: v1/v2/v3 aggregate flattening ------------------------

test("adaptCityRecord: v1 flat record is gsv-only, passed through", () => {
  const v1 = { city_id: "y--tx", city: "Y", pano_count: 42 };
  assert.equal(adaptCityRecord(v1, "gsv"), v1);
  assert.equal(adaptCityRecord(v1, "mapillary"), null);
});

test("adaptCityRecord: v2 gsv-only providers-less record", () => {
  const v2 = {
    city_id: "x--wa",
    city: { name: "X", state: "WA", country: "USA" },
    latest: {
      run_date: "2026-01-01",
      panorama_counts: { unique_panos: 10, unique_google_panos: 7 },
      histogram_of_capture_dates_by_year: {},
      all_panos_age_stats: {},
      coverage_rate_percent: 1,
      search_area_km2: 1,
      data_file: "a",
      json_file: "b",
    },
    runs: [{ run_date: "2026-01-01" }],
    change: null,
  };
  const gsv = adaptCityRecord(v2, "gsv");
  assert.equal(gsv.provider, "gsv");
  assert.equal(gsv.city, "X");
  assert.equal(gsv.pano_count, 7); // unique_google_panos preferred for gsv
  assert.equal(gsv.latest_run_date, "2026-01-01");
  // v2 has no providers map, so non-gsv views are absent.
  assert.equal(adaptCityRecord(v2, "mapillary"), null);
});

test("adaptCityRecord: v3 per-provider block, null when provider missing", () => {
  const v3 = {
    city_id: "bend--or",
    city: { name: "Bend", state: "OR", country: "USA" },
    providers: {
      gsv: {
        latest: {
          run_date: "2026-07-05",
          panorama_counts: { unique_panos: 100, unique_google_panos: 60 },
          histogram_of_capture_dates_by_year: {
            google_panos: { counts: { 2020: 5 } },
            all_panos: { counts: { 2020: 8 } },
          },
          google_panos_age_stats: { median_pano_age_years: 3 },
          all_panos_age_stats: { median_pano_age_years: 4 },
          coverage_rate_percent: 55,
          search_area_km2: 25,
          data_file: "c",
          json_file: "d",
        },
        runs: [{ run_date: "2026-01-01" }, { run_date: "2026-07-05" }],
        change: { from: "2026-01-01", panos_added: 5 },
      },
    },
  };
  const gsv = adaptCityRecord(v3, "gsv");
  assert.equal(gsv.pano_count, 60);
  assert.equal(gsv.runs.length, 2);
  assert.deepEqual(gsv.capture_year_histogram, { counts: { 2020: 5 } });
  // No mapillary block on this city → adapted record is null (omitted upstream).
  assert.equal(adaptCityRecord(v3, "mapillary"), null);
});

// --- isGoogleCopyright: exact © Google match -------------------------------

test("isGoogleCopyright: matches only the exact © Google string", () => {
  assert.equal(isGoogleCopyright("© Google"), true);
  // Photographer names can contain "Google" — must NOT match on substring.
  assert.equal(isGoogleCopyright("Google Street View contributor"), false);
  assert.equal(isGoogleCopyright("© Google, Inc"), false);
  assert.equal(isGoogleCopyright("© Jane Doe"), false);
  assert.equal(isGoogleCopyright(null), false);
  assert.equal(isGoogleCopyright(undefined), false);
  assert.equal(isGoogleCopyright(""), false);
});

// --- googleSharePercent: divide-by-zero guard (B1–B4) ----------------------

test("googleSharePercent: normal and 0-total (no Infinity%)", () => {
  assert.equal(googleSharePercent(60, 100), "60.0");
  assert.equal(googleSharePercent(1, 3), "33.3");
  // A 0-pano run must render "0.0", never "Infinity" or "NaN".
  assert.equal(googleSharePercent(0, 0), "0.0");
  assert.equal(googleSharePercent(3, 0), "0.0");
});

// --- buildFilledHistogram: empty/missing guard (#69) -----------------------

test("buildFilledHistogram: gap-fills through currentYear", () => {
  assert.deepEqual(buildFilledHistogram({ 2018: 2, 2020: 5 }, 2021), {
    2018: 2,
    2019: 0,
    2020: 5,
    2021: 0,
  });
});

test("buildFilledHistogram: empty/missing histogram yields {} (no Infinity loop)", () => {
  assert.deepEqual(buildFilledHistogram({}, 2021), {});
  assert.deepEqual(buildFilledHistogram(undefined, 2021), {});
  assert.deepEqual(buildFilledHistogram(null, 2021), {});
});

// --- panoDateOrNull: epoch guard (#122 / #69) ------------------------------

test("panoDateOrNull: falsy inputs return null, not the Unix epoch", () => {
  assert.equal(panoDateOrNull(null), null);
  assert.equal(panoDateOrNull(undefined), null);
  assert.equal(panoDateOrNull(""), null);
  assert.equal(panoDateOrNull(0), null);
});

test("panoDateOrNull: valid ISO date parses to a Date", () => {
  const d = panoDateOrNull("2020-06-15");
  assert.ok(d instanceof Date);
  assert.ok(!Number.isNaN(d.getTime()));
  assert.equal(d.getUTCFullYear(), 2020);
});
