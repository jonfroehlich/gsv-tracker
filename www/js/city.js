/* exported switchRun, toggleYear */
// (switchRun/toggleYear are invoked from onchange/onclick attributes in the
// HTML this file generates, so ESLint can't see those string references.)
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
  Object.values(markersByYear).flat().forEach((m) => m.addTo(map));
  updateLegend(Object.keys(markersByYear).map(Number));
});

// ── Legend (Leaflet control) ───────────────────────────────────
const legendControl = L.control({ position: "topright" });
legendControl.onAdd = () => L.DomUtil.create("div", "legend");
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
            <td>Panoramas</td>
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
    html += `<p class="legend-meta">Total panos: ${totalPanosGlobal.toLocaleString()}</p>`;
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

  if (changeGlobal) {
    const ch = changeGlobal;
    html += `
      <div class="legend-divider"></div>
      <div class="legend-year-header">Since ${escapeHtml(ch.from_run_date)}</div>
      <p class="legend-meta" style="margin:4px 0 0">
        <span style="color:#7bd88f">+${(ch.panos_added ?? 0).toLocaleString()} new</span> /
        <span style="color:#ff8a80">−${(ch.panos_removed ?? 0).toLocaleString()} removed</span>
        ${ch.capture_date_changed ? `<br>${ch.capture_date_changed.toLocaleString()} panos re-dated` : ""}
        ${ch.coverage_delta_pct != null ? `<br>Coverage ${ch.coverage_delta_pct >= 0 ? "+" : ""}${ch.coverage_delta_pct.toFixed(2)} pct pts` : ""}
      </p>`;
  }

  // ── Section 3: Interactive year filter ────────────────────
  if (sortedYears.length > 0) {
    html += `
      <div class="legend-divider"></div>
      <div class="legend-year-header">Filter by Year</div>`;

    sortedYears.forEach((year) => {
      const age = currentYear - year;
      const color = getColor(age, providerGlobal);
      const isActive = activeYears.has(year);
      const count = markersByYear[year]?.length || 0;

      html += `
        <div class="year-item ${isActive ? "active-item" : ""}">
          <i style="background:${color}" class="${isActive ? "active" : ""}"
             role="button" tabindex="0" aria-label="Toggle year ${year}"
             onclick="toggleYear(${year})"
             onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();toggleYear(${year})}"></i>
          ${year} <span class="year-count">(${count.toLocaleString()})</span>
        </div>`;
    });
  }

  div.innerHTML = html;
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
  Object.values(markersByYear).flat().forEach((m) => m.addTo(map));

  if (!wasActive) {
    activeYears.add(year);
    Object.entries(markersByYear).forEach(([y, markers]) => {
      if (parseInt(y, 10) !== year) markers.forEach((m) => m.remove());
    });
  }

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
 * Render a temporal scatter plot with vertical-line stems and
 * click-to-select date filtering.
 *
 * @param {Array<{date: Date, count: number}>} temporalData
 * @param {HTMLCanvasElement} canvas
 */
function createTemporalPlot(temporalData, canvas) {
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

  const currentYear = new Date().getFullYear();
  const chartData = {
    datasets: [{
      label: "Panoramas",
      data: temporalData.map((d) => ({ x: d.date, y: d.count, opacity: 1 })),
      backgroundColor: temporalData.map((d) => getColor(currentYear - d.date.getFullYear(), providerGlobal)),
      pointBackgroundColor: temporalData.map((d) => getColor(currentYear - d.date.getFullYear(), providerGlobal)),
      pointRadius: 4,
      pointHoverRadius: 6,
      pointBorderWidth: 0,
      pointStyle: "circle",
    }],
  };

  const chart = new Chart(canvas, {
    type: "scatter",
    data: chartData,
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          type: "time",
          time: { unit: "year", displayFormats: { year: "YYYY" } },
          grid: { display: false, color: "#888" },
          border: { color: "#888" },
          ticks: { color: "#999" },
          title: { color: "#999", display: true, text: "Capture Date" },
        },
        y: {
          grid: { display: false, color: "#888" },
          ticks: { color: "#999" },
          border: { color: "#888" },
          title: { color: "#999", display: true, text: "Num of Panoramas" },
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

  // Date-selection click handler
  canvas.addEventListener("click", (evt) => {
    const points = chart.getElementsAtEventForMode(evt, "nearest", { intersect: true }, true);

    if (points.length) {
      const data = chart.data.datasets[points[0].datasetIndex].data[points[0].index];
      const clickedDate = new Date(data.x);

      if (selectedDate && selectedDate.getTime() === clickedDate.getTime()) {
        selectedDate = null;
        resetMarkerStyles();
        resetChartColors(chart);
      } else {
        selectedDate = clickedDate;
        highlightMarkersForDate(selectedDate);
        updateChartColorsForDate(chart, selectedDate);
      }
    } else {
      selectedDate = null;
      resetMarkerStyles();
      resetChartColors(chart);
    }
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
    const base = getColor(age, providerGlobal);
    const opacity = ptDate.toDateString() === dateStr ? 1 : 0.3;
    pt.opacity = opacity;

    const match = base.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    return match
      ? `rgba(${match[1]}, ${match[2]}, ${match[3]}, ${opacity})`
      : base;
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
async function loadData() {
  if (!csvFile && !decodedCityQuery) {
    alert("Please provide either a file parameter or city parameter");
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
      const queryProvider = PROVIDERS[urlParams.get("provider")]
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
        progressContainer.style.display = "none";
        alert(result.error);
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
    const fmtYears = (v) => (v != null ? `${v.toFixed(1)} years` : "—");
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
    const progressStream = new TransformStream({
      transform(chunk, controller) {
        receivedBytes += chunk.length;
        const pct = Math.min((receivedBytes / totalBytes) * 100, 99);
        progressFill.style.width = `${pct}%`;
        progressFill.setAttribute("aria-valuenow", Math.round(pct));
        progressText.textContent =
          `Downloading ${fileSizeMB} MB for ${cityLabel}… ${Math.round(pct)}%`;
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
    const temporalMap = new Map(); // date string → count (replaces processTemporalData pass)

    /**
     * Process a batch of parsed CSV rows, creating map markers and
     * updating the temporal aggregation map.
     *
     * @param {Object[]} rows - PapaParse output rows.
     */
    function processRows(rows) {
      for (const row of rows) {
        if (
          row.status !== "OK" ||
          // GSV runs mix official and third-party imagery; show only
          // official Google. Other providers' rows are all provider panos.
          // Archival runs never recorded copyright, so all rows are kept.
          (providerGlobal === "gsv" && copyrightAvailableGlobal &&
            !isGoogleCopyright(row.copyright_info)) ||
          !row.capture_date ||
          !row.pano_id ||
          !row.pano_lat ||
          !row.pano_lon ||
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

        // Incremental temporal aggregation, keyed by the CSV's own
        // YYYY-MM-DD string (toISOString would shift local dates back to
        // the previous day east of UTC)
        const dateStr = String(row.capture_date);
        temporalMap.set(dateStr, (temporalMap.get(dateStr) || 0) + 1);

        // Map marker
        const marker = L.circleMarker([row.pano_lat, row.pano_lon], {
          radius: 3,
          fillColor: getColor(age, providerGlobal),
          color: "#000",
          weight: 0,
          opacity: 1,
          fillOpacity: 0.8,
          captureDate,
        }).addTo(map);

        const photographer = providerGlobal === "gsv"
          ? (copyrightAvailableGlobal ? "Google" : (row.copyright_info || "Unknown"))
          : (row.copyright_info || PROVIDERS[providerGlobal].label);
        marker.bindPopup(buildPopupHtml(captureDate, ageFormatted, row.pano_id,
                                        photographer));

        if (!markersByYear[year]) markersByYear[year] = [];
        markersByYear[year].push(marker);
        validPoints.push([row.pano_lat, row.pano_lon]);
      }
    }

    // Manual read loop — feeds string chunks to PapaParse.
    //
    // Each chunk from TextDecoderStream is a UTF-8 string of arbitrary
    // size that may split mid-row. We accumulate in `buffer` and flush
    // only complete lines (up to the last newline) to PapaParse, keeping
    // the header row prepended so every batch parses correctly.
    //
    // PapaParse handles RFC 4180 quoting (fields with embedded commas,
    // quotes, or newlines) correctly on each batch because it sees a
    // well-formed CSV fragment with headers on every call.

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
        const result = Papa.parse(`${headerLine}\n${completeText}`, {
          header: true,
          dynamicTyping: true,
          skipEmptyLines: true,
        });
        processRows(result.data);
      }
    }

    // ── Finalise ───────────────────────────────────────────────
    progressFill.style.width = "100%";
    progressFill.setAttribute("aria-valuenow", 100);
    progressContainer.style.display = "none";

    totalPanosGlobal = processedPanos.size;
    updateLegend(Object.keys(markersByYear).map(Number));

    const temporalData = Array.from(temporalMap.entries())
      .map(([d, c]) => ({ date: panoDateOrNull(d), count: c }))
      .sort((a, b) => a.date - b.date);

    createTemporalPlot(temporalData, document.getElementById("temporal-plot"));

    if (validPoints.length > 0) {
      map.fitBounds(L.latLngBounds(validPoints));
    }

  } catch (error) {
    console.error("Error loading or parsing city data:", error);
    progressContainer.style.display = "none";
    alert(`Failed to load city data: ${error.message}`);
  }
}

loadData();