/**
 * street-coverage.js
 * OSM street-coverage overlay for the per-city detail view (issue #24).
 *
 * Given a run's data filename, fetches the sibling
 * `{run_stem}_streets.json.gz` GeoJSON (written by
 * streetscape_street_analyzer.analyze) and draws each OSM street segment on
 * the map colored by coverage: segments with a nearby pano use the provider
 * age scale (matching the pano dots), segments without are drawn gray/dashed.
 * Also renders a "coverage by street type" panel — a headline plus a stacked
 * covered-vs-uncovered length chart.
 *
 * The artifact is optional: most cities have no streets file yet, so a missing
 * file is a silent no-op (the rest of the page is unaffected).
 *
 * Relies on globals from streetscape-utils.js: STREETSCAPE_DATA_BASE_URL,
 * PROVIDERS, getColor, fetchGzippedJson. Loaded before city.js, which calls
 * renderStreetCoverage().
 *
 * @module street-coverage
 */

/** Color for street segments with no imagery coverage. */
const STREET_UNCOVERED_COLOR = "#888";
/** Fallback color for covered segments whose nearest pano has no date. */
const STREET_COVERED_NODATE_COLOR = "#4caf50";

/**
 * Derive the streets artifact URL from a run's CSV filename.
 * Mirrors naming.streets_filename_for_run on the Python side — keep in sync.
 * @param {string} dataFile - e.g. "city_..._2026-07-06.csv.gz"
 * @returns {string} Full URL to the sibling "_streets.json.gz".
 */
function streetsUrlForDataFile(dataFile) {
  return STREETSCAPE_DATA_BASE_URL + dataFile.replace(/\.csv\.gz$/, "_streets.json.gz");
}

/**
 * Leaflet style for one street feature: covered segments use the provider
 * age color (like the pano dots); uncovered segments are gray and dashed.
 * @param {Object} feature - GeoJSON feature with coverage properties.
 * @param {string} provider - Provider key for the age color scale.
 * @returns {Object} Leaflet path style.
 */
function styleStreetFeature(feature, provider) {
  const p = feature.properties;
  if (!p.covered) {
    return { color: STREET_UNCOVERED_COLOR, weight: 2, opacity: 0.75, dashArray: "4 4" };
  }
  const age = p.nearest_pano_age_years;
  const color = age == null ? STREET_COVERED_NODATE_COLOR : getColor(age, provider);
  return { color, weight: 3, opacity: 0.9 };
}

/**
 * Fetch and render the street-coverage overlay and breakdown panel.
 * Silently returns if no streets artifact exists for this run.
 *
 * @param {L.Map} map - The Leaflet map (pano markers already added).
 * @param {string} dataFile - The active run's CSV filename.
 * @param {string} provider - Provider key ("gsv" | "mapillary").
 * @returns {Promise<void>}
 */
async function renderStreetCoverage(map, dataFile, provider) {
  let fc;
  try {
    fc = await fetchGzippedJson(streetsUrlForDataFile(dataFile));
  } catch (e) {
    console.info("No street-coverage artifact for this run (skipping):", e.message);
    return;
  }
  if (!fc || !fc.features || !fc.features.length) return;

  // Dedicated pane below the pano markers (overlayPane, z-index 400) so the
  // dots always draw on top of the street lines.
  if (!map.getPane("streetCoverage")) {
    map.createPane("streetCoverage");
    map.getPane("streetCoverage").style.zIndex = 250;
  }

  const layer = L.geoJSON(fc, {
    pane: "streetCoverage",
    style: (feature) => styleStreetFeature(feature, provider),
    onEachFeature: (feature, lyr) => {
      const p = feature.properties;
      const status = p.covered
        ? `covered${p.nearest_pano_date ? ` · ${p.nearest_pano_date}` : ""}`
        : "no coverage";
      lyr.bindTooltip(`${p.highway} · ${status}`, { sticky: true });
    },
  }).addTo(map);

  buildStreetCoveragePanel(map, layer, fc.properties.metadata, provider);
}

/**
 * Build the top-left panel: a headline, layer toggle, legend, and a stacked
 * covered-vs-uncovered length bar chart by street type.
 *
 * @param {L.Map} map - The map (for the show/hide toggle).
 * @param {L.GeoJSON} layer - The street layer to toggle.
 * @param {Object} meta - The artifact's `properties.metadata` block.
 * @param {string} provider - Provider key (for the human label).
 */
function buildStreetCoveragePanel(map, layer, meta, provider) {
  const container = document.getElementById("street-coverage-container");
  if (!container) return;
  const providerLabel = PROVIDERS[provider]?.label ?? provider;
  const totals = meta.totals;
  const byType = meta.coverage_by_highway;

  const uncoveredPct = totals.uncovered_pct_by_length;
  container.innerHTML = `
    <div id="street-coverage-header">
      <strong>Street coverage</strong>
      <label class="street-toggle">
        <input type="checkbox" id="street-layer-toggle" checked> show
      </label>
    </div>
    <p id="street-coverage-headline">
      <span class="street-headline-pct">${uncoveredPct}%</span> of street-km have
      no ${providerLabel} imagery
      <span class="street-headline-sub">
        (${totals.covered.toLocaleString()} of
        ${totals.segments.toLocaleString()} segments covered)
      </span>
    </p>
    <div class="street-legend">
      <span><i style="background:${STREET_COVERED_NODATE_COLOR}"></i>covered</span>
      <span><i style="background:${STREET_UNCOVERED_COLOR}"></i>no coverage</span>
    </div>
    <div id="street-chart-wrap"><canvas id="street-coverage-chart"></canvas></div>
  `;
  container.style.display = "block";

  document.getElementById("street-layer-toggle").addEventListener("change", (e) => {
    if (e.target.checked) layer.addTo(map);
    else map.removeLayer(layer);
  });

  const types = Object.keys(byType);
  const coveredKm = types.map((t) => byType[t].length_km_covered);
  const uncoveredKm = types.map((t) => byType[t].length_km - byType[t].length_km_covered);

  new Chart(document.getElementById("street-coverage-chart"), {
    type: "bar",
    data: {
      labels: types,
      datasets: [
        { label: "Covered", data: coveredKm, backgroundColor: STREET_COVERED_NODATE_COLOR },
        { label: "No coverage", data: uncoveredKm, backgroundColor: STREET_UNCOVERED_COLOR },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          stacked: true,
          title: { display: true, text: "Street length (km)", color: "#ddd" },
          ticks: { color: "#ccc" },
          grid: { color: "rgba(255,255,255,0.12)" },
        },
        y: { stacked: true, ticks: { color: "#ddd" }, grid: { display: false } },
      },
      plugins: {
        legend: { labels: { color: "#ddd", boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const t = byType[ctx.label];
              return ctx.datasetIndex === 0
                ? `Covered: ${t.length_km_covered.toFixed(1)} km (${t.coverage_pct_by_length}%)`
                : `No coverage: ${(t.length_km - t.length_km_covered).toFixed(1)} km`;
            },
          },
        },
      },
    },
  });
}

// Node/CommonJS export shim for the unit tests (issue #123). This is a no-op
// in the browser, where these symbols are plain globals loaded via <script>.
// renderStreetCoverage is exported for completeness (it needs Leaflet + DOM,
// so only the pure helpers are unit-tested).
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    streetsUrlForDataFile,
    styleStreetFeature,
    renderStreetCoverage,
    STREET_UNCOVERED_COLOR,
    STREET_COVERED_NODATE_COLOR,
  };
}
