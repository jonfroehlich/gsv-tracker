// Offline unit tests for the pure helpers in streetscape-utils.js (issue #123).
// Run with `npm test` (Node's built-in test runner) — no network, no jsdom,
// no browser. These cover the numeric/date edge cases behind the B1–B4
// tooltip bugs (Infinity%/NaN) and the 0-pano epoch-date bug (#122/#69).

const test = require("node:test");
const assert = require("node:assert/strict");

const {
  adaptCityRecord,
  escapeHtml,
  isValidRunFilename,
  isGoogleCopyright,
  panoDateOrNull,
  googleSharePercent,
  buildFilledHistogram,
} = require("../streetscape-utils.js");

// --- adaptCityRecord: v1/v2/v3 aggregate flattening ------------------------

// A REAL v1 record, mirroring generate_aggregate_summary_as_json's output:
// flat fields, `city` is a bare string, data_file is an object, and NONE of
// the normalized keys (provider/pano_count/pano_age_stats/
// capture_year_histogram) exist. Regression: the adapter used to pass v1
// records through raw, so index.js crashed on
// pano_age_stats.median_pano_age_years with a live pre-v2 cities.json.gz.
const V1_RECORD = {
  city: "Bellingham",
  state: { name: "Washington", code: "WA" },
  country: { name: "United States", code: "us" },
  center: { latitude: 48.75, longitude: -122.48 },
  bounds: { northeast: {}, southwest: {} },
  data_file: {
    filename: "bellingham--wa_width_5000_height_5000_step_20.csv.gz",
    size_bytes: 12345,
  },
  search_area_km2: 25,
  coverage_rate_percent: 51.2,
  panorama_counts: { unique_panos: 100, unique_google_panos: 60 },
  all_panos_age_stats: { median_pano_age_years: 4.2 },
  google_panos_age_stats: { median_pano_age_years: 3.1 },
  collection_info: { start_time: "t0", end_time: "t1", duration_seconds: 60 },
  histogram_of_capture_dates_by_year: {
    all_panos: { 2019: 40, 2020: 60 },
    google_panos: { 2019: 25, 2020: 35 },
  },
};

test("adaptCityRecord: real v1 record gains the normalized keys", () => {
  const gsv = adaptCityRecord(V1_RECORD, "gsv");
  assert.equal(gsv.provider, "gsv");
  // Normalized keys derived from the flat v1 fields, preferring the
  // official-Google subset (same rule as v2/v3).
  assert.equal(gsv.pano_count, 60);
  assert.equal(gsv.pano_age_stats.median_pano_age_years, 3.1);
  assert.deepEqual(gsv.capture_year_histogram, { 2019: 25, 2020: 35 });
  // Fields the UI iterates/branches on must exist even though v1 lacks them.
  assert.deepEqual(gsv.runs, []);
  assert.equal(gsv.change, null);
  assert.equal(gsv.copyright_info_available, true);
  // Historical flat fields survive untouched (index.js reads
  // data_file.filename and the bare-string city name).
  assert.equal(gsv.city, "Bellingham");
  assert.equal(gsv.data_file.filename, V1_RECORD.data_file.filename);
  // v1 is gsv-only.
  assert.equal(adaptCityRecord(V1_RECORD, "mapillary"), null);
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

// --- escapeHtml: XSS guard for data-derived strings -------------------------

test("escapeHtml: neutralizes markup in third-party strings", () => {
  // A hostile Mapillary contributor name must not survive as markup.
  assert.equal(
    escapeHtml('<img src=x onerror=alert(1)>'),
    "&lt;img src=x onerror=alert(1)&gt;"
  );
  assert.equal(
    escapeHtml(`"quoted" & 'single' <tag>`),
    "&quot;quoted&quot; &amp; &#39;single&#39; &lt;tag&gt;"
  );
  // Benign strings pass through unchanged.
  assert.equal(escapeHtml("© Mapillary contributor 42"), "© Mapillary contributor 42");
});

test("escapeHtml: non-string inputs are safe", () => {
  assert.equal(escapeHtml(null), "");
  assert.equal(escapeHtml(undefined), "");
  assert.equal(escapeHtml(12345), "12345");
});

// --- isValidRunFilename: ?file= URL-parameter validation --------------------

test("isValidRunFilename: accepts every run-filename generation", () => {
  // Legacy undated
  assert.ok(isValidRunFilename("bend--or_width_5000_height_5000_step_20.csv.gz"));
  // Buggy float step
  assert.ok(isValidRunFilename("bend--or_width_5000_height_5000_step_20.0.csv.gz"));
  // Dated, tokenless (gsv)
  assert.ok(isValidRunFilename("bend--or_width_5000_height_5000_step_20_2026-07-05.csv.gz"));
  // Dated, provider-tagged
  assert.ok(
    isValidRunFilename("bend--or_width_5000_height_5000_step_20_mapillary_2026-07-05.csv.gz")
  );
  // Slug with interior period (st.-louis rule)
  assert.ok(
    isValidRunFilename("st.-louis--mo_width_5000_height_5000_step_20_2026-07-05.csv.gz")
  );
});

test("isValidRunFilename: rejects traversal and non-run artifacts", () => {
  // Path traversal / separators — the attack the validator exists for.
  assert.equal(isValidRunFilename("../../../etc/passwd"), false);
  assert.equal(
    isValidRunFilename("../other/x_width_1_height_1_step_1_2026-01-01.csv.gz"),
    false
  );
  assert.equal(
    isValidRunFilename("a\\b_width_1_height_1_step_1_2026-01-01.csv.gz"),
    false
  );
  // URL metacharacters that could smuggle a query/fragment.
  assert.equal(
    isValidRunFilename("a?b_width_1_height_1_step_1_2026-01-01.csv.gz"),
    false
  );
  // Non-run artifacts: diff files, history files, working files.
  assert.equal(isValidRunFilename("bend--or_diff_2026-04-01_to_2026-07-01.csv.gz"), false);
  assert.equal(
    isValidRunFilename("bend--or_width_5000_height_5000_step_20_gsv_history_2026-07-05.csv.gz"),
    false
  );
  assert.equal(
    isValidRunFilename("bend--or_width_5000_height_5000_step_20_2026-07-05.csv.gz.rejected"),
    false
  );
  assert.equal(isValidRunFilename("cities.json.gz"), false);
  assert.equal(isValidRunFilename(""), false);
  assert.equal(isValidRunFilename(null), false);
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
