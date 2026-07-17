/* exported switchRun, toggleYear, setGsvMode */
// (switchRun/toggleYear/setGsvMode are invoked from onchange/onclick
// attributes in the HTML this file generates, so ESLint can't see those
// string references.)
/**
 * city.js
 * Per-city detail-view logic for Streetscape City Explorer.
 *
 * Depends on globals from streetscape-utils.js: PROVIDERS, getColor,
 * getProviderFromFilename, fetchGzippedJson, adaptCitiesPayload,
 * STREETSCAPE_DATA_BASE_URL. The imagery provider (GSV vs Mapillary) is derived
 * from the data filename's provider token.
 *
 * Third-party libraries (loaded via CDN in city.html):
 *   Leaflet, Chart.js, moment, chartjs-adapter-moment, PapaParse, pako
 *
 * Streaming architecture:
 *   The CSV data files for large cities can exceed 200 MB uncompressed.
 *   We use the native browser DecompressionStream + TextDecoderStream to
 *   inflate on the fly, then manually drive a read loop that feeds string
 *   chunks to PapaParse. This avoids both the pako RangeError (single
 *   giant string) and PapaParse's unsupported WHATWG ReadableStream input.
 *
 * @module city
 */

// ── Map setup ──────────────────────────────────────────────────
// preferCanvas: pano markers render on a shared <canvas> instead of one
// SVG DOM node each — the difference between usable and frozen for large
// cities (10⁵+ markers).
const map = L.map("map", { zoomControl: false, preferCanvas: true }).setView([0, 0], 13);
L.control.zoom({ position: "bottomleft" }).addTo(map);

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: "© OpenStreetMap contributors © CARTO",
  maxZoom: 19,
}).addTo(map);

// ── Module-level state ─────────────────────────────────────────
let markersByYear = {};
let activeYears = new Set();
let selectedDate = null;
let cityNameGlobal = "";
let stateNameGlobal = "";
let totalPanosGlobal = 0;
let collectionDateGlobal = "";
let statsGlobal = null;
let panoStatsGlobal = null; // provider pano block: google_panos (gsv) or all_panos
let copyrightAvailableGlobal = true; // false for archival GSV runs with no copyright data
let providerGlobal = "gsv"; // derived from the data filename
let oldestDateGlobal = null;
let newestDateGlobal = null;

// GSV imagery display mode. Every run streams BOTH official-Google and
// contributor (UGC) panos into markers; `showAllGsv` is a pure display
// switch: false (default) hides the contributor markers, true reveals them.
// Never set for non-GSV providers (their rows are all provider imagery) or
// archival GSV runs that recorded no copyright (Google vs UGC unknown).
let showAllGsv = false;

// Temporal-plot handles, kept at module scope so setGsvMode() can rebuild the
// plot in place (updating the existing chart/handlers rather than re-creating
// them and duplicating the keyboard listeners / live region).
let temporalChartGlobal = null;
let temporalDataGlobal = [];
let temporalKeyboardIdx = -1;

// panoDateOrNull() and isGoogleCopyright() are shared helpers from streetscape-utils.js
// (loaded first), reused here for the info-panel dates and the © Google filter.
let runsGlobal = [];        // this city's run history from the aggregate
let currentFileGlobal = ""; // csv.gz filename of the run being displayed
let changeGlobal = null;    // change_from_previous_run block of this run

// ── Map interaction ────────────────────────────────────────────

// Reset selection when clicking the map background.
map.on("click", (e) => {
  if (e.originalEvent.target !== map._container) return;
  selectedDate = null;
  Object.values(markersByYear).flat().forEach((m) => {
    m.setStyle({ fillOpacity: 0.8 });
    m.setRadius(3);
  });
  activeYears.clear();
  showInModeMarkers();
  updateLegend(Object.keys(markersByYear).map(Number));
});

/**
 * Whether a marker belongs in the current GSV display mode. Contributor
 * (non-official-Google) GSV markers are shown only in "All GSV" mode; every
 * Google marker — and every non-GSV/archival marker, which is tagged
 * isGoogle:true since the distinction doesn't apply — is always eligible.
 * Year- and date-filters compose on top of this base visibility.
 *
 * @param {L.CircleMarker} m
 * @returns {boolean}
 */
function markerInMode(m) {
  return m.options.isGoogle || showAllGsv;
}

/**
 * Add every in-mode marker to the map and remove every out-of-mode one.
 * The single place that reconciles the drawn marker set with `showAllGsv`;
 * callers that clear a year/date filter delegate the "show everything again"
 * step here so contributor markers stay hidden in Google-only mode.
 */
function showInModeMarkers() {
  Object.values(markersByYear).flat().forEach((m) => {
    if (markerInMode(m)) m.addTo(map);
    else m.remove();
  });
}

// ── Legend (Leaflet control) ───────────────────────────────────
const legendControl = L.control({ position: "topright" });
legendControl.onAdd = () => {
  const div = L.DomUtil.create("div", "legend");
  // Keep legend interaction local: without these, clicking a year toggle
  // also fires the map's click handler and scrolling the legend zooms
  // the map underneath it.
  L.DomEvent.disableClickPropagation(div);
  L.DomEvent.disableScrollPropagation(div);
  return div;
};
legendControl.addTo(map);

/**
 * Rebuild the legend HTML to reflect the current marker state.
 * Renders two sections: a data overview table and an interactive year filter.
 *
 * @param {Iterable<number>} years - Set or array of years present in data.
 */
function updateLegend(years) {
  const div = document.querySelector(".legend");
  const currentYear = new Date().getFullYear();
  const sortedYears = Array.from(years).sort((a, b) => b - a);

  // ── Section 1: Data overview ───────────────────────────────
  // City/state names originate in OSM/Nominatim (publicly editable) via
  // the run's JSON metadata — escape before injecting.
  let html = `<h4>${escapeHtml(cityNameGlobal)}${stateNameGlobal ? `, ${escapeHtml(stateNameGlobal)}` : ""}</h4>`;

  if (statsGlobal) {
    const s = statsGlobal;
    const fmt = (v) => (v != null ? v.toFixed(1) : "—");
    const oldest = oldestDateGlobal?.toLocaleDateString() ?? "—";
    const newest = newestDateGlobal?.toLocaleDateString() ?? "—";
    const median = fmt(panoStatsGlobal.age_stats.median_pano_age_years);
    const avg    = fmt(panoStatsGlobal.age_stats.avg_pano_age_years);
    const sd     = fmt(panoStatsGlobal.age_stats.stdev_pano_age_years);

    html += `
      <table class="legend-stats" aria-label="Dataset statistics">
        <tbody>
          <tr>
            <td>Collected</td>
            <td>${collectionDateGlobal || "Unknown"}</td>
          </tr>
          <tr>
            <td>Dated panoramas</td>
            <td>${totalPanosGlobal.toLocaleString()}</td>
          </tr>
          <tr>
            <td>Grid area</td>
            <td>${s.search_grid.area_km2.toFixed(1)} km²</td>
          </tr>
          <tr>
            <td>Search points</td>
            <td>${s.search_grid.total_search_points.toLocaleString()}</td>
          </tr>
          <tr>
            <td>Step size</td>
            <td>${s.search_grid.step_length_meters} m</td>
          </tr>
          <tr class="legend-stats-divider">
            <td>Oldest pano</td>
            <td>${oldest}</td>
          </tr>
          <tr>
            <td>Newest pano</td>
            <td>${newest}</td>
          </tr>
          <tr>
            <td>Median age</td>
            <td>${median} yrs</td>
          </tr>
          <tr>
            <td>Avg age</td>
            <td>${avg} yrs <span class="legend-stats-sd">(±${sd})</span></td>
          </tr>
        </tbody>
      </table>`;
  } else {
    html += `<p class="legend-meta">Dated panos: ${totalPanosGlobal.toLocaleString()}</p>`;
  }

  // ── Section 2: Snapshot history (v2 temporal data) ────────
  if (runsGlobal.length > 1) {
    const options = runsGlobal
      .slice()
      .reverse() // newest first
      .map((r) => {
        const selected = r.data_file === currentFileGlobal ? " selected" : "";
        return `<option value="${escapeHtml(r.data_file)}"${selected}>${escapeHtml(r.run_date)}${r.is_baseline ? " (baseline)" : ""}</option>`;
      })
      .join("");
    html += `
      <div class="legend-divider"></div>
      <div class="legend-year-header">
        <label for="run-select">Snapshot (${runsGlobal.length} runs)</label>
      </div>
      <select id="run-select" aria-label="Select collection snapshot"
              style="width:100%;margin-top:4px"
              onchange="switchRun(this.value)">${options}</select>`;
  }

  const change = formatChangeSummary(changeGlobal);
  if (change) {
    html += `
      <div class="legend-divider"></div>
      <div class="legend-year-header">Since ${escapeHtml(change.from)}</div>
      <p class="legend-meta" style="margin:4px 0 0">
        <span style="color:#7bd88f">${change.added}</span> /
        <span style="color:#ff8a80">${change.removed}</span>
        ${change.redated ? `<br>${change.redated}` : ""}
        ${change.coverage ? `<br>Coverage ${change.coverage}` : ""}
      </p>`;
  }

  // ── Section 3: GSV imagery mode toggle ────────────────────
  // Only for GSV runs that recorded copyright (so Google vs contributor is
  // known). Both marker sets are already in memory — this flips which are
  // drawn without any refetch. Other providers' rows are all provider
  // imagery, so there is nothing to toggle.
  if (providerGlobal === "gsv" && copyrightAvailableGlobal) {
    const allMarkers = Object.values(markersByYear).flat();
    const allCount = allMarkers.length;
    const googleCount = allMarkers.filter((m) => m.options.isGoogle).length;
    html += `
      <div class="legend-divider"></div>
      <div class="legend-year-header">Imagery</div>
      <div class="gsv-mode-toggle" role="radiogroup" aria-label="Google Street View imagery filter">
        <button type="button" class="gsv-mode-btn ${!showAllGsv ? "active" : ""}"
                role="radio" aria-checked="${!showAllGsv}"
                onclick="setGsvMode(false)">
          Google only <span class="year-count">(${googleCount.toLocaleString()})</span>
        </button>
        <button type="button" class="gsv-mode-btn ${showAllGsv ? "active" : ""}"
                role="radio" aria-checked="${showAllGsv}"
                onclick="setGsvMode(true)">
          All GSV <span class="year-count">(${allCount.toLocaleString()})</span>
        </button>
      </div>`;
  }

  // ── Section 4: Interactive year filter ────────────────────
  if (sortedYears.length > 0) {
    html += `
      <div class="legend-divider"></div>
      <div class="legend-year-header">Filter by Year</div>`;

    sortedYears.forEach((year) => {
      const age = currentYear - year;
      const color = getColor(age, providerGlobal);
      const isActive = activeYears.has(year);
      // Count only markers visible in the current mode, so the year rows
      // never advertise contributor panos that are hidden in Google-only.
      const count = (markersByYear[year] || []).filter(markerInMode).length;
      if (count === 0) return; // a year that is all-contributor drops out in Google-only mode

      // Real <button>s (native Enter/Space + focus) with aria-pressed
      // toggle state; the color swatch is decorative.
      html += `
        <button type="button" class="year-item ${isActive ? "active-item" : ""}"
                data-year="${year}" aria-pressed="${isActive}"
                aria-label="Filter to year ${year}, ${count.toLocaleString()} panoramas"
                onclick="toggleYear(${year})">
          <i style="background:${color}" class="${isActive ? "active" : ""}"
             aria-hidden="true"></i>
          ${year} <span class="year-count">(${count.toLocaleString()})</span>
        </button>`;
    });
  }

  // Replacing innerHTML destroys the focused element; if focus was on a
  // year button, put it back on the same year so keyboard users don't get
  // dropped to <body> on every toggle.
  const focusedYear = div.contains(document.activeElement)
    ? document.activeElement.dataset?.year
    : null;
  div.innerHTML = html;
  if (focusedYear != null) {
    div.querySelector(`.year-item[data-year="${focusedYear}"]`)?.focus();
  }
}

/**
 * Navigate to another snapshot of the same city (full reload keeps the
 * streaming pipeline simple — each run is its own csv.gz/json.gz pair).
 *
 * @param {string} dataFile - csv.gz filename of the selected run.
 */
function switchRun(dataFile) {
  if (dataFile && dataFile !== currentFileGlobal) {
    window.location.href = `city.html?file=${encodeURIComponent(dataFile)}`;
  }
}

/**
 * Toggle visibility of markers for a single year. Re-clicking the
 * active year restores all years.
 *
 * @param {number} year
 */
function toggleYear(year) {
  const wasActive = activeYears.has(year);
  activeYears.clear();
  showInModeMarkers();

  if (!wasActive) {
    activeYears.add(year);
    Object.entries(markersByYear).forEach(([y, markers]) => {
      if (parseInt(y, 10) !== year) markers.forEach((m) => m.remove());
    });
  }

  updateLegend(Object.keys(markersByYear).map(Number));
}

/**
 * Switch the GSV imagery display mode between official-Google-only (default)
 * and all GSV (Google + contributor/UGC panos).
 *
 * A pure display switch: every contributor marker is already streamed into
 * memory, so this only shows/hides them and recomputes the derived views
 * (overview stats, dated-pano count, year filter, temporal plot) from the
 * matching JSON block and the in-memory markers — no network request. Any
 * active year/date filter is cleared, since its marker set is mode-specific.
 * No-op for non-GSV providers and archival GSV runs (no toggle is shown).
 *
 * @param {boolean} showAll - true = All GSV, false = Google only.
 */
function setGsvMode(showAll) {
  if (providerGlobal !== "gsv" || !copyrightAvailableGlobal) return;
  if (showAll === showAllGsv) return;
  showAllGsv = showAll;

  // Swap the stats block that drives the legend overview (age stats,
  // oldest/newest). Both blocks are present in the run JSON for GSV.
  panoStatsGlobal = showAllGsv
    ? statsGlobal.all_panos
    : (statsGlobal.google_panos ?? statsGlobal.all_panos);
  oldestDateGlobal = panoDateOrNull(panoStatsGlobal.age_stats.oldest_pano_date);
  newestDateGlobal = panoDateOrNull(panoStatsGlobal.age_stats.newest_pano_date);

  // Clear the year/date filters and reconcile the drawn marker set with the
  // new mode. resetMarkerStyles undoes any dimming left by an active date
  // filter; refreshTemporalPlot rebuilds the plot with fresh (un-dimmed)
  // colors, so the chart needs no separate reset.
  activeYears.clear();
  selectedDate = null;
  resetMarkerStyles();
  showInModeMarkers();

  totalPanosGlobal = Object.values(markersByYear).flat().filter(markerInMode).length;
  refreshTemporalPlot();
  updateLegend(Object.keys(markersByYear).map(Number));
}

// ── URL parameters ─────────────────────────────────────────────
const urlParams = new URLSearchParams(window.location.search);
// ?file= is untrusted input concatenated onto the data base URL, so it is
// validated against the filename contract (isValidRunFilename): anything
// else — path traversal, non-run artifacts — is treated as absent.
const rawCsvFileParam = urlParams.get("file");
const csvFile = isValidRunFilename(rawCsvFileParam) ? rawCsvFileParam : null;
if (rawCsvFileParam && !csvFile) {
  console.warn("Ignoring invalid ?file= parameter:", rawCsvFileParam);
}
const cityQuery = urlParams.get("city");
const decodedCityQuery = cityQuery
  ? decodeURIComponent(cityQuery).replace(/^"(.*)"$/, "$1")
  : null;

// ── Fuzzy-matching helpers ─────────────────────────────────────

/**
 * Compute the Levenshtein edit distance between two strings.
 *
 * @param {string} a
 * @param {string} b
 * @returns {number}
 */
function levenshteinDistance(a, b) {
  if (a.length === 0) return b.length;
  if (b.length === 0) return a.length;

  const matrix = [];
  for (let i = 0; i <= b.length; i++) matrix[i] = [i];
  for (let j = 0; j <= a.length; j++) matrix[0][j] = j;

  for (let i = 1; i <= b.length; i++) {
    for (let j = 1; j <= a.length; j++) {
      matrix[i][j] = b[i - 1] === a[j - 1]
        ? matrix[i - 1][j - 1]
        : Math.min(matrix[i - 1][j - 1], matrix[i][j - 1], matrix[i - 1][j]) + 1;
    }
  }
  return matrix[b.length][a.length];
}

/**
 * Parse a user-supplied location query string into structured components.
 *
 * @param {string} query - e.g. "Seattle, WA" or "Paris, France".
 * @param {Object} citiesData - Full cities.json payload (used to
 *   disambiguate whether the second token is a state or country).
 * @returns {{city: string, state: ?string, country: ?string}|null}
 */
function parseLocationQuery(query, citiesData) {
  if (!query || typeof query !== "string") return null;

  const parts = query.trim().split(",").map((p) => p.trim());

  if (parts.length === 3) {
    return { city: parts[0], state: parts[1], country: parts[2] };
  }

  if (parts.length === 2) {
    const cityPart = parts[0];
    const id = parts[1].toLowerCase();

    const stateIds = new Set();
    const countryIds = new Set();
    citiesData.cities.forEach((c) => {
      if (c.state?.code) stateIds.add(c.state.code.toLowerCase());
      if (c.state?.name) stateIds.add(c.state.name.toLowerCase());
      if (c.country?.code) countryIds.add(c.country.code.toLowerCase());
      if (c.country?.name) countryIds.add(c.country.name.toLowerCase());
    });

    const isState = stateIds.has(id);
    const isCountry = countryIds.has(id);

    if (isCountry && !isState) return { city: cityPart, state: null, country: id };
    return { city: cityPart, state: id, country: null };
  }

  if (parts.length === 1) {
    return { city: parts[0], state: null, country: null };
  }

  return null;
}

/**
 * Find the best fuzzy-matching city record for a parsed location query,
 * using weighted Levenshtein distances.
 *
 * @param {Object} parsedQuery - From {@link parseLocationQuery}.
 * @param {Object} citiesData - Full cities.json payload.
 * @param {number} [maxDistance=3] - Maximum acceptable weighted distance.
 * @returns {{match: Object, distance: number}|{match: null, error: string, suggestions: Object[]}}
 */
function findBestMatchingCity(parsedQuery, citiesData, maxDistance = 3) {
  if (!parsedQuery?.city) {
    return {
      match: null,
      error: "Invalid query format. Please use 'City, State', 'City, Country', or 'City, State, Country' format.",
    };
  }

  let bestMatch = null;
  let bestDistance = Infinity;
  const scored = [];

  citiesData.cities.forEach((cityData) => {
    const cityDist = levenshteinDistance(
      parsedQuery.city.toLowerCase(),
      (cityData.city || "").toLowerCase()
    );
    let total = cityDist * 2;

    if (parsedQuery.state) {
      const codeDist = levenshteinDistance(parsedQuery.state.toLowerCase(), (cityData.state?.code || "").toLowerCase());
      const nameDist = levenshteinDistance(parsedQuery.state.toLowerCase(), (cityData.state?.name || "").toLowerCase());
      total += Math.min(codeDist, nameDist);
    }

    if (parsedQuery.country) {
      const codeDist = levenshteinDistance(parsedQuery.country.toLowerCase(), (cityData.country?.code || "").toLowerCase());
      const nameDist = levenshteinDistance(parsedQuery.country.toLowerCase(), (cityData.country?.name || "").toLowerCase());
      total += Math.min(codeDist, nameDist);
    }

    scored.push({ city: cityData, totalDistance: total });

    if (total < bestDistance) {
      bestDistance = total;
      bestMatch = cityData;
    }
  });

  if (bestDistance > maxDistance) {
    scored.sort((a, b) => a.totalDistance - b.totalDistance);
    const suggestions = scored.slice(0, 3).map((s) => ({
      city: s.city.city,
      state: s.city.state?.code,
      country: s.city.country?.code,
    }));
    return {
      match: null,
      error: suggestions.length
        ? "No close matches found. Did you mean:\n" + suggestions.map((s) => [s.city, s.state, s.country].filter(Boolean).join(", ")).join("\n")
        : "No close matches found.",
      suggestions,
    };
  }

  return { match: bestMatch, distance: bestDistance };
}

// ── Temporal plot ──────────────────────────────────────────────

/**
 * Aggregate the in-mode markers into per-capture-date counts for the
 * temporal scatter plot. Reads the markers already on the map (respecting the
 * GSV Google-only/all mode) rather than a separate pass, so the plot and the
 * map always describe the same pano set. Keyed by each marker's original
 * YYYY-MM-DD capture-date string to avoid the UTC/local shift that would move
 * January/year-precision dates into the previous year.
 *
 * @returns {Array<{date: Date, count: number}>} Sorted oldest-first.
 */
function buildTemporalData() {
  const counts = new Map();
  Object.values(markersByYear).flat().forEach((m) => {
    if (!markerInMode(m)) return;
    const key = m.options.captureDateStr;
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return Array.from(counts.entries())
    .map(([d, c]) => ({ date: panoDateOrNull(d), count: c }))
    .sort((a, b) => a.date - b.date);
}

/**
 * Build the Chart.js dataset for a temporalData array (points colored by
 * capture-year age on the active provider's scale).
 *
 * @param {Array<{date: Date, count: number}>} temporalData
 * @returns {Object} A Chart.js scatter dataset.
 */
function buildTemporalDataset(temporalData) {
  const currentYear = new Date().getFullYear();
  return {
    label: "Panoramas",
    data: temporalData.map((d) => ({ x: d.date, y: d.count, opacity: 1 })),
    backgroundColor: temporalData.map((d) => getColor(currentYear - d.date.getFullYear(), providerGlobal)),
    pointBackgroundColor: temporalData.map((d) => getColor(currentYear - d.date.getFullYear(), providerGlobal)),
    pointRadius: 4,
    pointHoverRadius: 6,
    pointBorderWidth: 0,
    pointStyle: "circle",
  };
}

/**
 * Rebuild the temporal plot from the current in-mode markers, updating the
 * existing chart in place. Used after a GSV mode switch — recreating the
 * chart would duplicate the canvas click/keyboard listeners and the live
 * region, so we only swap the dataset and reset the keyboard cursor.
 */
function refreshTemporalPlot() {
  if (!temporalChartGlobal) return;
  temporalDataGlobal = buildTemporalData();
  temporalChartGlobal.data.datasets[0] = buildTemporalDataset(temporalDataGlobal);
  temporalKeyboardIdx = -1;
  temporalChartGlobal.update();
}

/**
 * Render a temporal scatter plot with vertical-line stems and
 * click-to-select date filtering. Called once per page load; later mode
 * switches go through refreshTemporalPlot(). The chart handle and its plotted
 * data live at module scope (temporalChartGlobal/temporalDataGlobal) so the
 * interaction handlers and refreshTemporalPlot() share them.
 *
 * @param {HTMLCanvasElement} canvas
 */
function createTemporalPlot(canvas) {
  const verticalLinePlugin = {
    id: "verticalLines",
    beforeDraw: (chart) => {
      const ctx = chart.ctx;
      const xAxis = chart.scales.x;
      const yAxis = chart.scales.y;

      chart.data.datasets[0].data.forEach((point, i) => {
        const x = xAxis.getPixelForValue(point.x);
        ctx.save();
        ctx.beginPath();
        ctx.strokeStyle = chart.data.datasets[0].backgroundColor[i];
        ctx.globalAlpha = point.opacity === undefined ? 1 : point.opacity;
        ctx.lineWidth = 3;
        ctx.moveTo(x, yAxis.getPixelForValue(point.y));
        ctx.lineTo(x, yAxis.getPixelForValue(0));
        ctx.stroke();
        ctx.restore();
      });
    },
  };

  temporalDataGlobal = buildTemporalData();

  const chart = new Chart(canvas, {
    type: "scatter",
    data: { datasets: [buildTemporalDataset(temporalDataGlobal)] },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        // Tick/title color: #ccc on the rgba(80,80,80,.9) panel ≈ 6:1
        // contrast (#999 was ~2.9:1, below WCAG AA).
        x: {
          type: "time",
          time: { unit: "year", displayFormats: { year: "YYYY" } },
          grid: { display: false, color: "#888" },
          border: { color: "#888" },
          ticks: { color: "#ccc" },
          title: { color: "#ccc", display: true, text: "Capture Date" },
        },
        y: {
          grid: { display: false, color: "#888" },
          ticks: { color: "#ccc" },
          border: { color: "#888" },
          title: { color: "#ccc", display: true, text: "Num of Panoramas" },
          beginAtZero: true,
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          enabled: true,
          mode: "nearest",
          intersect: true,
          callbacks: {
            label: (ctx) =>
              `Date: ${moment(ctx.raw.x).format("MM/DD/YYYY")}, Count: ${ctx.raw.y}`,
          },
        },
      },
    },
    plugins: [verticalLinePlugin],
  });
  temporalChartGlobal = chart;

  /** Apply (or toggle off) the date filter for one capture date. */
  function selectFilterDate(date) {
    if (selectedDate && date && selectedDate.getTime() === date.getTime()) {
      date = null; // re-selecting the active date clears the filter
    }
    selectedDate = date;
    if (date) {
      highlightMarkersForDate(date);
      updateChartColorsForDate(chart, date);
    } else {
      resetMarkerStyles();
      resetChartColors(chart);
    }
  }

  // Date-selection click handler
  canvas.addEventListener("click", (evt) => {
    const points = chart.getElementsAtEventForMode(evt, "nearest", { intersect: true }, true);
    if (points.length) {
      const data = chart.data.datasets[points[0].datasetIndex].data[points[0].index];
      selectFilterDate(new Date(data.x));
    } else {
      selectFilterDate(null);
    }
  });

  // Keyboard path to the same filter — canvas points can't be tabbed to.
  // Left/Right step through capture dates, Home/End jump, Escape clears.
  // Selections are announced through a visually-hidden live region.
  canvas.setAttribute("tabindex", "0");
  canvas.setAttribute("role", "application");
  canvas.setAttribute("aria-label",
    "Panoramas by capture date. Use Left and Right arrow keys to filter the map by date, Escape to clear the filter.");

  const liveRegion = document.createElement("div");
  liveRegion.className = "visually-hidden";
  liveRegion.setAttribute("aria-live", "polite");
  canvas.parentElement.appendChild(liveRegion);

  // temporalKeyboardIdx / temporalDataGlobal are module-level so a GSV mode
  // switch (which reassigns them via refreshTemporalPlot) is reflected here
  // without re-registering this listener.
  canvas.addEventListener("keydown", (e) => {
    if (temporalDataGlobal.length === 0) return;

    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      const delta = e.key === "ArrowRight" ? 1 : -1;
      temporalKeyboardIdx = temporalKeyboardIdx === -1
        ? (delta === 1 ? 0 : temporalDataGlobal.length - 1)
        : Math.min(Math.max(temporalKeyboardIdx + delta, 0), temporalDataGlobal.length - 1);
    } else if (e.key === "Home") {
      e.preventDefault();
      temporalKeyboardIdx = 0;
    } else if (e.key === "End") {
      e.preventDefault();
      temporalKeyboardIdx = temporalDataGlobal.length - 1;
    } else if (e.key === "Escape") {
      e.preventDefault();
      temporalKeyboardIdx = -1;
      selectFilterDate(null);
      liveRegion.textContent = "Date filter cleared";
      return;
    } else {
      return;
    }

    const d = temporalDataGlobal[temporalKeyboardIdx];
    selectedDate = null; // force re-apply even if the same date is revisited
    selectFilterDate(d.date);
    liveRegion.textContent =
      `${d.date.toLocaleDateString()}: ${d.count.toLocaleString()} panoramas highlighted`;
  });
}

// ── Marker / chart style helpers ───────────────────────────────

/** Reset all map markers to their default style. */
function resetMarkerStyles() {
  Object.values(markersByYear).flat().forEach((m) => {
    m.setStyle({ fillOpacity: 0.8 });
    m.setRadius(3);
  });
}

/**
 * Highlight only map markers whose capture date matches the given date.
 *
 * @param {Date} date
 */
function highlightMarkersForDate(date) {
  const dateStr = date.toDateString();
  Object.values(markersByYear).flat().forEach((m) => {
    const match = new Date(m.options.captureDate).toDateString() === dateStr;
    m.setStyle({ fillOpacity: match ? 1 : 0.05 });
    m.setRadius(match ? 4 : 3);
  });
}

/**
 * Reset chart point colors and opacities to defaults.
 *
 * @param {Chart} chart - The Chart.js instance.
 */
function resetChartColors(chart) {
  const ds = chart.data.datasets[0];
  ds.data.forEach((pt) => { pt.opacity = 1; });
  ds.backgroundColor = ds.data.map((pt) => {
    const age = new Date().getFullYear() - new Date(pt.x).getFullYear();
    return getColor(age, providerGlobal);
  });
  ds.pointBackgroundColor = ds.backgroundColor;
  chart.update();
}

/**
 * Dim chart points that don't match the selected date.
 *
 * @param {Chart} chart - The Chart.js instance.
 * @param {Date} date - The selected date.
 */
function updateChartColorsForDate(chart, date) {
  const ds = chart.data.datasets[0];
  const dateStr = date.toDateString();

  ds.backgroundColor = ds.data.map((pt) => {
    const ptDate = new Date(pt.x);
    const age = new Date().getFullYear() - ptDate.getFullYear();
    const opacity = ptDate.toDateString() === dateStr ? 1 : 0.3;
    pt.opacity = opacity;
    return withAlpha(getColor(age, providerGlobal), opacity);
  });

  ds.pointBackgroundColor = ds.backgroundColor;
  chart.update();
}

// ── Main data loading ──────────────────────────────────────────

/**
 * Build a popup HTML string for a panorama marker, deep-linking to the
 * active provider's pano viewer.
 *
 * @param {Date} captureDate
 * @param {string} ageFormatted - Human-readable age string.
 * @param {string} panoId
 * @param {string} photographer - e.g. "Google" or a Mapillary contributor.
 * @returns {string} HTML string.
 */
function buildPopupHtml(captureDate, ageFormatted, panoId, photographer) {
  const provider = PROVIDERS[providerGlobal];
  // photographer is third-party content (Mapillary contributor names,
  // archival GSV credits) and pano_id comes straight from the CSV — both
  // must be escaped before entering popup HTML.
  return `
    <div style="font-family:sans-serif">
      <strong>Capture Date:</strong> ${captureDate.toLocaleDateString()}<br>
      <strong>Age:</strong> ${ageFormatted}<br>
      <strong>Photographer:</strong> ${escapeHtml(photographer)}<br>
      <strong>Pano ID:</strong> ${escapeHtml(panoId)}<br><br>
      <a href="${provider.viewerUrl(panoId)}"
         target="_blank" rel="noopener"
         style="color:#2196F3;text-decoration:none">
         ${provider.viewerLabel}
      </a>
    </div>
  `;
}

/**
 * Load, decompress, and parse the CSV data file for the target city.
 *
 * Uses a native browser streaming pipeline to avoid V8's string-length
 * limit on large files:
 *
 *   fetch → TransformStream (progress) → DecompressionStream → TextDecoderStream
 *                                                                      ↓
 *                                              manual reader.read() loop
 *                                                                      ↓
 *                                          PapaParse (fed string chunks)
 *
 * PapaParse does not support WHATWG ReadableStream as a direct input in
 * browser environments (only Node.js streams). We therefore drive the
 * read loop ourselves and hand PapaParse plain strings, which correctly
 * handles quoted fields (e.g. copyright_info values containing commas).
 *
 * Progress is tracked against the *compressed* byte count reported in
 * the city metadata JSON, giving an accurate download percentage.
 */
/**
 * Show a load error in the progress panel. Replaces the old alert(),
 * which blocked the page and left no trace once dismissed; the panel
 * stays visible next to the "Back to Overview Map" link.
 *
 * @param {string} message
 */
function showLoadError(message) {
  document.getElementById("progress-bar").style.display = "none";
  document.getElementById("progress-container").style.display = "block";
  document.getElementById("progress-text").textContent = message;
}

async function loadData() {
  if (!csvFile && !decodedCityQuery) {
    showLoadError("No city specified — open this page from the overview map, "
      + "or add ?file= or ?city= to the URL.");
    return;
  }

  // The streaming pipeline needs the native DecompressionStream
  // (Safari < 16.4 lacks it). Fail with a clear message instead of a
  // ReferenceError mid-download.
  if (typeof DecompressionStream === "undefined") {
    showLoadError("This browser can't stream the map data (it lacks "
      + "DecompressionStream). Please use a current Chrome, Firefox, Edge, "
      + "or Safari 16.4+.");
    return;
  }

  const progressContainer = document.getElementById("progress-container");
  const progressFill = document.getElementById("progress-fill");
  const progressText = document.getElementById("progress-text");

  try {
    progressContainer.style.display = "block";

    let targetFile = csvFile;

    // Fetch the aggregate: needed to resolve ?city= queries, and to find
    // this city's run history for the snapshot selector.
    let rawCities = null;
    let citiesData = null;
    try {
      progressText.textContent = "Loading city index…";
      rawCities = await fetchGzippedJson(STREETSCAPE_DATA_BASE_URL + "cities.json.gz");
      // ?city= queries resolve against the requested provider's view
      // (?provider=mapillary), defaulting to GSV
      const queryProvider = isKnownProvider(urlParams.get("provider"))
        ? urlParams.get("provider") : "gsv";
      citiesData = adaptCitiesPayload(rawCities, queryProvider);
    } catch (e) {
      // The ?file= path can still work without the aggregate
      console.warn("Could not load cities.json.gz:", e);
    }

    // Resolve city query → filename via the aggregate
    if (!csvFile && decodedCityQuery) {
      if (!citiesData) throw new Error("City index unavailable; cannot resolve ?city= query");
      progressText.textContent = `Finding city data for: ${decodedCityQuery}`;
      const parsedQuery = parseLocationQuery(decodedCityQuery, citiesData);
      const result = findBestMatchingCity(parsedQuery, citiesData);
      if (!result.match) {
        showLoadError(result.error);
        return;
      }
      targetFile = result.match.data_file.filename;
    }

    currentFileGlobal = targetFile;
    providerGlobal = getProviderFromFilename(targetFile);
    map.attributionControl.addAttribution(PROVIDERS[providerGlobal].attribution);

    // Locate this city's run history for the snapshot selector — only the
    // active provider's runs, so the <select> never mixes provider series
    if (rawCities) {
      const providerCities = adaptCitiesPayload(rawCities, providerGlobal).cities;
      const record = providerCities.find((c) =>
        c.data_file?.filename === targetFile ||
        (c.runs || []).some((r) => r.data_file === targetFile));
      if (record) runsGlobal = record.runs || [];
    }

    // Load city-specific JSON metadata
    progressText.textContent = "Loading city metadata…";
    const metadataUrl = STREETSCAPE_DATA_BASE_URL + targetFile.replace(".csv.gz", ".json.gz");
    const stats = await fetchGzippedJson(metadataUrl);
    changeGlobal = stats.change_from_previous_run || null;

    const totalBytes = stats.data_file.size_bytes;
    const fileSizeMB = (totalBytes / (1024 * 1024)).toFixed(1);
    const cityName = stats.city.name;
    const stateName = stats.city.state?.name ?? null;
    const cityLabel = stateName ? `${cityName}, ${stateName}` : cityName;

    cityNameGlobal = cityName;
    stateNameGlobal = stateName ?? "";
    collectionDateGlobal = stats.download?.end_time
      ? new Date(stats.download.end_time).toLocaleDateString()
      : "";

    // Populate global stats for legend overview (available before streaming
    // starts). For GSV the provider block is the Google-copyright subset;
    // other providers' all_panos rows are already all provider imagery.
    statsGlobal = stats;
    copyrightAvailableGlobal = stats.copyright_info_available !== false;
    panoStatsGlobal = stats.google_panos ?? stats.all_panos;
    oldestDateGlobal = panoDateOrNull(panoStatsGlobal.age_stats.oldest_pano_date);
    newestDateGlobal = panoDateOrNull(panoStatsGlobal.age_stats.newest_pano_date);

    // Draw city bounds outline
    const bounds = stats.city.bounds;
    const regionCoords = [
      [bounds.min_lat, bounds.min_lon],
      [bounds.min_lat, bounds.max_lon],
      [bounds.max_lat, bounds.max_lon],
      [bounds.max_lat, bounds.min_lon],
    ];

    const oldestDate = panoDateOrNull(panoStatsGlobal.age_stats.oldest_pano_date);
    const newestDate = panoDateOrNull(panoStatsGlobal.age_stats.newest_pano_date);

    const googleLine = stats.google_panos
      ? `Google panoramas: ${stats.google_panos.duplicate_stats.total_unique_panos.toLocaleString()}<br>`
      : "";
    const copyrightNote = !copyrightAvailableGlobal
      ? `<em>Copyright info not recorded (archival import); counts include all panoramas</em><br>`
      : "";
    // fmtYears comes from streetscape-utils.js
    const tooltipHtml = `
      <div style="font-family:sans-serif">
        <strong>${escapeHtml(cityLabel)}</strong><br>
        <em>${PROVIDERS[providerGlobal].label}</em><br><br>
        Total panoramas: ${stats.all_panos.duplicate_stats.total_unique_panos.toLocaleString()}<br>
        ${googleLine}${copyrightNote}<br>
        Search grid area: ${stats.search_grid.area_km2.toFixed(1)} km²<br>
        Total search points: ${stats.search_grid.total_search_points.toLocaleString()}<br>
        Grid step size: ${stats.search_grid.step_length_meters} meters<br><br>
        Oldest pano: ${oldestDate ? oldestDate.toLocaleDateString() : "—"}<br>
        Newest pano: ${newestDate ? newestDate.toLocaleDateString() : "—"}<br>
        Median age: ${fmtYears(panoStatsGlobal.age_stats.median_pano_age_years)}<br>
        Average age: ${fmtYears(panoStatsGlobal.age_stats.avg_pano_age_years)}
        ${panoStatsGlobal.age_stats.stdev_pano_age_years != null ? `(SD=${panoStatsGlobal.age_stats.stdev_pano_age_years.toFixed(1)} years)` : ""}<br><br>
        Data collected: ${collectionDateGlobal || "Unknown"}
      </div>
    `;

    L.polygon(regionCoords, {
      color: "cyan",
      weight: 2,
      opacity: 0.8,
      fill: false,
    }).addTo(map).bindTooltip(tooltipHtml, { sticky: true, opacity: 0.9, direction: "auto" });

    // ── Streaming pipeline ─────────────────────────────────────
    //
    // Architecture:
    //   fetch response.body (Uint8Array chunks)
    //     → TransformStream  — counts compressed bytes for progress bar
    //     → DecompressionStream("gzip")  — native browser inflate
    //     → TextDecoderStream  — Uint8Array → UTF-8 string chunks
    //     → reader.read() loop  — feeds string chunks to PapaParse
    //
    // Why not Papa.parse(stream, ...)?
    //   PapaParse's ReadableStream support targets Node.js streams only.
    //   Passing a WHATWG ReadableStream throws a TypeError in _readChunk.

    const response = await fetch(STREETSCAPE_DATA_BASE_URL + targetFile);
    if (!response.ok) throw new Error(`HTTP ${response.status} fetching ${targetFile}`);

    let receivedBytes = 0;
    let lastShownPct = -1;
    const progressStream = new TransformStream({
      transform(chunk, controller) {
        receivedBytes += chunk.length;
        // Only touch the DOM when the whole percent changes — this fires
        // per network chunk (thousands of times on a big city)
        const pct = Math.min(Math.round((receivedBytes / totalBytes) * 100), 99);
        if (pct !== lastShownPct) {
          lastShownPct = pct;
          progressFill.style.width = `${pct}%`;
          progressFill.setAttribute("aria-valuenow", pct);
          progressText.textContent =
            `Downloading ${fileSizeMB} MB for ${cityLabel}… ${pct}%`;
        }
        controller.enqueue(chunk);
      },
    });

    const reader = response.body
      .pipeThrough(progressStream)
      .pipeThrough(new DecompressionStream("gzip"))
      .pipeThrough(new TextDecoderStream())
      .getReader();

    // Per-parse state
    const currentYear = new Date().getFullYear();
    const processedPanos = new Set();
    const validPoints = [];

    /**
     * Process a batch of parsed CSV rows, creating a map marker per pano.
     *
     * GSV runs mix official-Google and contributor (UGC) imagery. Both are
     * kept and tagged with `isGoogle` so the "GSV imagery" toggle can reveal
     * or hide the contributor markers with no refetch; only Google markers
     * are drawn initially (Google-only is the default mode). Other providers'
     * rows are all provider imagery, and archival runs recorded no copyright,
     * so those are tagged isGoogle:true (always in-mode). The temporal plot is
     * built later from the in-mode markers (buildTemporalData), so there is no
     * incremental temporal pass here.
     *
     * @param {Object[]} rows - PapaParse output rows.
     */
    function processRows(rows) {
      for (const row of rows) {
        if (
          row.status !== "OK" ||
          !row.capture_date ||
          !row.pano_id ||
          // == null, not falsy: 0.0 is a valid coordinate (equator/meridian)
          row.pano_lat == null ||
          row.pano_lon == null ||
          processedPanos.has(row.pano_id)
        ) continue;

        processedPanos.add(row.pano_id);

        // panoDateOrNull parses date-only strings as LOCAL midnight so the
        // year bucket/color matches the calendar date in the CSV (a UTC
        // parse shifted Jan/year-precision dates into the previous year
        // for visitors west of UTC).
        const captureDate = panoDateOrNull(row.capture_date);
        if (!captureDate || isNaN(captureDate.getTime())) continue; // skip unparseable dates

        const year = captureDate.getFullYear();
        const age = currentYear - year;
        const ageInYears = (Date.now() - captureDate) / (1000 * 60 * 60 * 24 * 365.25);
        const ageFormatted = ageInYears < 1
          ? `${Math.round(ageInYears * 12)} months`
          : `${ageInYears.toFixed(1)} years`;

        // Official-Google iff the copyright matches exactly (see
        // isGoogleCopyright). Non-GSV/archival rows have no such distinction
        // and are treated as always-visible.
        const isGoogle = providerGlobal !== "gsv" || !copyrightAvailableGlobal
          || isGoogleCopyright(row.copyright_info);

        // Map marker. captureDateStr keeps the CSV's own YYYY-MM-DD string so
        // buildTemporalData can re-bucket by local date without a UTC shift.
        const marker = L.circleMarker([row.pano_lat, row.pano_lon], {
          radius: 3,
          fillColor: getColor(age, providerGlobal),
          color: "#000",
          weight: 0,
          opacity: 1,
          fillOpacity: 0.8,
          captureDate,
          captureDateStr: String(row.capture_date),
          isGoogle,
        });
        if (markerInMode(marker)) marker.addTo(map);

        const photographer = providerGlobal !== "gsv"
          ? (row.copyright_info || PROVIDERS[providerGlobal].label)
          : !copyrightAvailableGlobal
            ? (row.copyright_info || "Unknown")
            : isGoogle ? "Google" : (row.copyright_info || "Contributor");
        marker.bindPopup(buildPopupHtml(captureDate, ageFormatted, row.pano_id,
                                        photographer));

        if (!markersByYear[year]) markersByYear[year] = [];
        markersByYear[year].push(marker);
        if (markerInMode(marker)) validPoints.push([row.pano_lat, row.pano_lon]);
      }
    }

    // Manual read loop — feeds string chunks to PapaParse.
    //
    // Each chunk from TextDecoderStream is a UTF-8 string of arbitrary
    // size that may split mid-row. We accumulate in `buffer` and flush
    // only complete lines (up to the last newline) to PapaParse, keeping
    // the header row prepended so every batch parses correctly.
    //
    // PapaParse handles quoted fields with embedded commas or quotes
    // correctly on each batch because it sees a well-formed CSV fragment
    // with headers on every call. Caveat: a quoted field containing a
    // literal NEWLINE would be split across batches by the lastIndexOf
    // splitter above. That can't occur here — the writers (METADATA_DTYPES
    // schema, standardize_capture_date, pandas to_csv defaults) never emit
    // multi-line field values.

    // Per-column typing: only coordinates are numeric. Blanket
    // dynamicTyping would coerce pano_id to a float — Mapillary IDs are
    // numeric strings that can exceed 2^53 and would silently round,
    // corrupting the dedup set and viewer deep-links.
    const csvParseOptions = {
      header: true,
      dynamicTyping: { query_lat: true, query_lon: true, pano_lat: true, pano_lon: true },
      skipEmptyLines: true,
    };

    let buffer = "";
    let headerLine = null; // first line of the CSV (column names)

    while (true) {
      const { done, value } = await reader.read();

      if (done) {
        // Flush any remaining content after the last newline
        if (buffer.trim() && headerLine !== null) {
          const result = Papa.parse(`${headerLine}\n${buffer}`, csvParseOptions);
          processRows(result.data);
        }
        break;
      }

      buffer += value;

      // Only process complete lines; hold back any partial trailing line
      const lastNewline = buffer.lastIndexOf("\n");
      if (lastNewline === -1) continue; // no complete line yet

      const completeText = buffer.slice(0, lastNewline + 1);
      buffer = buffer.slice(lastNewline + 1);

      if (headerLine === null) {
        // First chunk: extract the header line, parse remainder
        const firstNewline = completeText.indexOf("\n");
        if (firstNewline === -1) {
          // Entire first chunk is still just the header (very unlikely)
          headerLine = completeText.trimEnd();
          continue;
        }
        headerLine = completeText.slice(0, firstNewline);
        const dataText = completeText.slice(firstNewline + 1);
        if (dataText.trim()) {
          const result = Papa.parse(`${headerLine}\n${dataText}`, csvParseOptions);
          processRows(result.data);
        }
      } else {
        // Same options as the first chunk — a blanket dynamicTyping here
        // would coerce pano_id to a float on every later chunk (Mapillary
        // IDs exceed 2^53 and silently round).
        const result = Papa.parse(`${headerLine}\n${completeText}`, csvParseOptions);
        processRows(result.data);
      }
    }

    // ── Finalise ───────────────────────────────────────────────
    progressFill.style.width = "100%";
    progressFill.setAttribute("aria-valuenow", 100);
    progressContainer.style.display = "none";

    // Dated-pano count reflects the current mode (Google-only by default);
    // it and the plot are recomputed from the in-mode markers, matching what
    // is drawn on the map.
    totalPanosGlobal = Object.values(markersByYear).flat().filter(markerInMode).length;
    updateLegend(Object.keys(markersByYear).map(Number));

    createTemporalPlot(document.getElementById("temporal-plot"));

    if (validPoints.length > 0) {
      map.fitBounds(L.latLngBounds(validPoints));
    }

  } catch (error) {
    console.error("Error loading or parsing city data:", error);
    showLoadError(`Failed to load city data: ${error.message}`);
  }
}

loadData();