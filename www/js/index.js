/**
 * index.js
 * Overview-map logic for Streetscape City Explorer.
 *
 * Depends on globals from streetscape-utils.js (PROVIDERS, getColor,
 * fetchGzippedJson, adaptCitiesPayload, STREETSCAPE_DATA_BASE_URL) and the
 * Leaflet / Chart.js libraries.
 */

// ── Global state ──────────────────────────────────────────────
const map = L.map("map").setView([0, 0], 2);
const charts = { pano: null, area: null };
const mapRectangles = [];
let allCityBounds = null;
let rawCitiesData = null; // the fetched cities.json.gz payload (all providers)

// The one live popup histogram. Popups are content-functions (built on
// open), so at most one Chart exists at a time — destroyed on close,
// otherwise each open leaks a Chart instance + ResizeObserver.
let activePopupChart = null;
map.on("popupclose", () => {
  activePopupChart?.destroy();
  activePopupChart = null;
});

// Active provider, persisted in the URL (?provider=mapillary)
const providerParam = new URLSearchParams(window.location.search).get("provider");
let currentProvider = isKnownProvider(providerParam) ? providerParam : "gsv";

// Fill color for cities with no age data (0 dated panos → null median).
// Previously they fell through getColor(null) → 0 years → newest-yellow,
// indistinguishable from genuinely fresh coverage.
const NO_DATA_COLOR = "#666666";

L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
  attribution: "© OpenStreetMap contributors © CARTO",
  maxZoom: 19,
}).addTo(map);

// ── Popup histogram ───────────────────────────────────────────

/**
 * Create a bar-chart canvas showing panorama counts by capture year.
 *
 * @param {Object<number, number>} histogramData - Year → count mapping.
 * @param {number} currentYear - Current calendar year (for age coloring).
 * @returns {HTMLCanvasElement}
 */
function createPopupHistogram(histogramData, currentYear) {
  const canvas = document.createElement("canvas");
  canvas.setAttribute("role", "img");
  canvas.setAttribute("aria-label",
    `Bar chart of ${PROVIDERS[currentProvider].panoNoun} by capture year`);
  const years = Object.keys(histogramData).map(Number).sort((a, b) => a - b);
  const counts = years.map((y) => histogramData[y]);
  const ages = years.map((y) => currentYear - y);

  activePopupChart = new Chart(canvas, {
    type: "bar",
    data: {
      labels: years,
      datasets: [{
        data: counts,
        backgroundColor: ages.map((a) => getColor(a, currentProvider)),
        borderColor: "rgba(0,0,0,0.2)",
        borderWidth: 1,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: { display: true,
                 text: `${PROVIDERS[currentProvider].panoNoun} by Capture Year` },
      },
      scales: {
        y: { beginAtZero: true, title: { display: true, text: "Panoramas" } },
        x: { title: { display: true, text: "Capture Year" } },
      },
    },
  });

  return canvas;
}

// ── Popup tooltip ─────────────────────────────────────────────

/**
 * Build a DOM element used as a Leaflet popup for a city rectangle.
 *
 * @param {Object} city - City record from cities.json.
 * @returns {HTMLElement}
 */
function createTooltip(city) {
  const container = document.createElement("div");
  container.style.minWidth = "250px";

  const panoStats = city.panorama_counts;
  const ageStats = city.pano_age_stats;

  // For GSV, break out the official-Google share of all found panoramas;
  // for other providers every pano is already provider imagery
  let panoLinesHtml = `<li>Total Panoramas: ${panoStats.unique_panos.toLocaleString()}</li>`;
  if (city.provider === "gsv" && panoStats.unique_google_panos != null) {
    // googleSharePercent guards the 0-pano divide-by-zero "Infinity%" (#69).
    const googlePct = googleSharePercent(
      panoStats.unique_google_panos, panoStats.unique_panos);
    panoLinesHtml += `<li>Google Panoramas: ${panoStats.unique_google_panos.toLocaleString()} (${googlePct}%)</li>`;
  }

  // Snapshot history line (schema v2): "3 snapshots since 2025-01-17"
  let snapshotsHtml = "";
  if (city.runs && city.runs.length > 0) {
    const n = city.runs.length;
    snapshotsHtml = `<li>Snapshots: ${n} (since ${escapeHtml(city.runs[0].run_date)})</li>`;
  }

  // Change-since-last-run line (schema v2), colored by direction
  let changeHtml = "";
  const change = formatChangeSummary(city.change);
  if (change) {
    changeHtml = `
      <div style="margin-top:12px"><strong>Since ${escapeHtml(change.from)}:</strong></div>
      <ul class="popup-stats-list">
        <li><span style="color:#2e7d32">${change.added}</span> /
            <span style="color:#c62828">${change.removed}</span> panoramas</li>
        ${change.redated ? `<li>${change.redated}</li>` : ""}
        ${change.coverage ? `<li>Coverage: ${change.coverage}</li>` : ""}
      </ul>`;
  }

  // City/state/country names come from OSM/Nominatim (publicly editable
  // third-party data) — escape everything data-derived entering innerHTML.
  container.innerHTML = `
    <h3>${escapeHtml(getCityLabel(city))}</h3>
    <strong>Coverage Statistics:</strong>
    <ul class="popup-stats-list">
      <li>Data Collected: ${escapeHtml(city.latest_run_date) || (city.collection_info?.end_time ? new Date(city.collection_info.end_time).toLocaleDateString() : "Unknown")}</li>
      ${snapshotsHtml}
      <li>Area: ${city.search_area_km2.toFixed(1)} km²</li>
      ${panoLinesHtml}
    </ul>
    <div style="margin-top:12px"><strong>Age Statistics:</strong></div>
    <ul class="popup-stats-list">
      <li>Median Age: ${ageStats.median_pano_age_years != null ? ageStats.median_pano_age_years.toFixed(1) + " years" : "No data"}</li>
      <li>Average Age: ${ageStats.avg_pano_age_years != null ? ageStats.avg_pano_age_years.toFixed(1) + " years" : "No data"}
        ${ageStats.stdev_pano_age_years != null ? ` (SD=${ageStats.stdev_pano_age_years.toFixed(1)})` : ""}</li>
      <li>Newest: ${panoDateOrNull(ageStats.newest_pano_date)?.toLocaleDateString() ?? "No data"}</li>
      <li>Oldest: ${panoDateOrNull(ageStats.oldest_pano_date)?.toLocaleDateString() ?? "No data"}</li>
    </ul>
    ${changeHtml}
  `;

  // Histogram chart
  const chartContainer = document.createElement("div");
  chartContainer.className = "popup-chart-container";

  const currentYear = new Date().getFullYear();
  // capture_year_histogram may be a {counts: {...}} wrapper, a bare year→count
  // map, or missing entirely for an empty run — buildFilledHistogram tolerates
  // all three (and the Math.min([]) === Infinity empty-run case, #69).
  const rawHistogram =
    city.capture_year_histogram?.counts || city.capture_year_histogram;
  const filledHistogram = buildFilledHistogram(rawHistogram, currentYear);

  chartContainer.appendChild(createPopupHistogram(filledHistogram, currentYear));
  container.appendChild(chartContainer);

  // "View Detailed Analysis" button
  const btnWrap = document.createElement("div");
  btnWrap.style.textAlign = "right";
  btnWrap.style.marginTop = "12px";

  const link = document.createElement("a");
  link.href = `city.html?file=${encodeURIComponent(city.data_file.filename)}`;
  link.target = "_blank";
  link.rel = "noopener";
  link.className = "view-details-btn";
  link.textContent = "View Detailed Analysis";
  btnWrap.appendChild(link);
  container.appendChild(btnWrap);

  return container;
}

// ── Legend ─────────────────────────────────────────────────────

/**
 * Populate the legend panel with one row per integer-age bucket, plus a
 * non-interactive "No age data" row when any city lacks a median age.
 *
 * @param {number} maxAge - Maximum median age across all cities.
 * @param {Object[]} cities - Array of city records.
 */
function createLegend(maxAge, cities) {
  const legend = document.getElementById("legend");
  const maxYears = Math.ceil(maxAge);

  const ageCounts = new Array(maxYears + 1).fill(0);
  let noDataCount = 0;
  cities.forEach((city) => {
    const median = city.pano_age_stats.median_pano_age_years;
    if (median == null) {
      noDataCount++;
      return;
    }
    const age = Math.floor(median);
    if (age <= maxYears) ageCounts[age]++;
  });

  let html = "<h4>Median Age (years)</h4>";
  for (let age = 0; age <= maxYears; age++) {
    const color = getColor(age, currentProvider);
    const n = ageCounts[age];
    const label = n > 0 ? `(${n} ${n === 1 ? "city" : "cities"})` : "(no cities)";

    // Real <button>s: native Enter/Space activation and focus handling,
    // with aria-pressed carrying the toggle state.
    html += `
      <button type="button" class="legend-item" data-age="${age}"
              aria-pressed="false"
              aria-label="Highlight cities with median age ${age} year${age !== 1 ? "s" : ""} ${label}">
        <span class="legend-color" style="background:${color}" aria-hidden="true"></span>
        ${age} year${age !== 1 ? "s" : ""} ${label}
      </button>`;
  }
  if (noDataCount > 0) {
    html += `
      <div class="legend-item">
        <span class="legend-color" style="background:${NO_DATA_COLOR}" aria-hidden="true"></span>
        No age data (${noDataCount})
      </div>`;
  }
  legend.innerHTML = html;

  // Click handlers (the "No age data" row is a plain div and stays
  // non-interactive; buttons handle keyboard activation natively)
  legend.querySelectorAll("button.legend-item").forEach((item) => {
    item.addEventListener("click", () => {
      const isAlreadySelected = item.classList.contains("selected");

      // Clear selection from all items
      legend.querySelectorAll("button.legend-item").forEach((i) => {
        i.classList.remove("selected");
        i.setAttribute("aria-pressed", "false");
      });

      if (isAlreadySelected) {
        resetHighlights();
      } else {
        item.classList.add("selected");
        item.setAttribute("aria-pressed", "true");
        highlightCitiesByExactAge(parseInt(item.dataset.age, 10));
      }
    });
  });
}

// ── Highlighting helpers ──────────────────────────────────────

/**
 * Dim everything except cities whose floored median age matches
 * {@link targetAge}.
 *
 * @param {number} targetAge
 * @param {boolean} [zoomToHighlightedCities=false]
 */
function highlightCitiesByExactAge(targetAge) {
  const tolerance = 0.5;
  lastHighlightedCity = AGE_BUCKET_HIGHLIGHT; // supersedes any hover

  [charts.pano, charts.area].forEach((chart) => {
    const ds = chart.data.datasets[0];
    ds.pointBackgroundColor = ds.data.map((pt) => {
      const age = Math.floor(pt.y);
      return Math.abs(age - targetAge) <= tolerance
        ? pt.backgroundColor
        : withAlpha(pt.backgroundColor, 0.3);
    });
    ds.pointRadius = ds.data.map((pt) =>
      Math.abs(Math.floor(pt.y) - targetAge) <= tolerance ? 6 : 3
    );
    ds.borderWidth = ds.data.map((pt) =>
      Math.abs(Math.floor(pt.y) - targetAge) <= tolerance ? 2 : 0
    );
    ds.borderColor = ds.data.map((pt) =>
      Math.abs(Math.floor(pt.y) - targetAge) <= tolerance
        ? "rgba(0,0,0,0.8)" : "rgba(0,0,0,0)"
    );
    chart.update();
  });

  mapRectangles.forEach((rect) => {
    const median = rect.city.pano_age_stats.median_pano_age_years;
    // Null median (no age data) never matches an age bucket
    const age = median != null ? Math.floor(median) : NaN;
    if (Math.abs(age - targetAge) <= tolerance) {
      // Selected state
      rect.setStyle({
        fillOpacity: 0.8,
        weight: 2,
        opacity: 1
      });
      rect.bringToFront();
    } else {
      // Unselected state: significantly more "faded"
      rect.setStyle({
        fillOpacity: 0.1, // Very faint fill
        weight: 0.1,       // Thin borders
        opacity: 0.2       // Faded borders
      });
    }
  });
}

// The current highlight state: null (defaults), a city record (hover), or
// AGE_BUCKET_HIGHLIGHT (legend selection). Hover events fire per mousemove;
// restyling ~1,100 rectangles and updating two charts on every one froze
// the map, so highlightCity/resetHighlights no-op when nothing changed.
const AGE_BUCKET_HIGHLIGHT = Symbol("age-bucket");
let lastHighlightedCity = null;

/**
 * Highlight a single city across both scatter charts and the map.
 *
 * @param {Object} city - The city record to highlight.
 */
function highlightCity(city) {
  if (city === lastHighlightedCity) return;
  lastHighlightedCity = city;

  [charts.pano, charts.area].forEach((chart) => {
    const ds = chart.data.datasets[0];
    ds.pointBackgroundColor = ds.data.map((pt) =>
      pt.city === city ? pt.backgroundColor : withAlpha(pt.backgroundColor, 0.3)
    );
    ds.pointRadius = ds.data.map((pt) => (pt.city === city ? 6 : 3));
    ds.borderWidth = ds.data.map((pt) => (pt.city === city ? 2 : 0));
    ds.borderColor = ds.data.map((pt) =>
      pt.city === city ? "rgba(0,0,0,0.8)" : "rgba(0,0,0,0)"
    );
    chart.update();
  });

  mapRectangles.forEach((rect) => {
    rect.setStyle(rect.city === city
      ? { fillOpacity: 0.8, weight: 2 }
      : { fillOpacity: 0.2, weight: 1 });
  });
}

/** Reset all chart and map highlights back to their defaults. */
function resetHighlights() {
  if (lastHighlightedCity === null) return;
  lastHighlightedCity = null;

  [charts.pano, charts.area].forEach((chart) => {
    const ds = chart.data.datasets[0];
    ds.pointBackgroundColor = ds.data.map((pt) => pt.backgroundColor);
    ds.pointRadius = ds.data.map(() => 4);
    ds.borderWidth = ds.data.map(() => 1);
    ds.borderColor = ds.data.map(() => "rgba(0,0,0,0.2)");
    chart.update();
  });

  mapRectangles.forEach((rect) => {
    rect.setStyle({ fillOpacity: 0.6, weight: 1 });
  });
}

// ── City search ──────────────────────────────────────────────

/**
 * Build the display label for a city record.
 * @param {Object} city
 * @returns {string}  e.g. "Seattle, Washington, United States"
 */
function getCityLabel(city) {
  const name = city.city || city.state?.name || city.country?.name || "Unknown";
  const parts = [name];
  if (city.state?.name && city.state.name !== name) parts.push(city.state.name);
  if (city.country?.name) parts.push(city.country.name);
  return parts.join(", ");
}

/**
 * Select a city: highlight it on map & charts, zoom to it, and open
 * its popup.
 * @param {Object} city
 */
function selectCity(city) {
  // Highlight across all visualizations
  highlightCity(city);

  // Animated zoom to the city rectangle with some padding
  const b = city.bounds;
  const latSpan = b.max_lat - b.min_lat;
  const lonSpan = b.max_lon - b.min_lon;
  const pad = Math.max(latSpan, lonSpan) * 3;
  map.flyToBounds([
    [b.min_lat - pad, b.min_lon - pad],
    [b.max_lat + pad, b.max_lon + pad],
  ], { duration: 1.2 });

  // Open the popup after the animation finishes
  const rect = mapRectangles.find((r) => r.city === city);
  if (rect) {
    map.once("moveend", () => rect.openPopup());
  }
}

// Search state shared across provider re-renders: the entry list is
// swapped per provider, but DOM listeners are attached exactly once.
let searchEntries = [];
let searchInitialized = false;

/**
 * Initialise (or, on provider switch, re-populate) the city search
 * autocomplete. Safe to call repeatedly.
 * @param {Object[]} cities - Array of city records.
 */
function initCitySearch(cities) {
  // Pre-compute labels and sort alphabetically
  searchEntries = cities
    .map((city) => ({ city, label: getCityLabel(city) }))
    .sort((a, b) => a.label.localeCompare(b.label));

  if (searchInitialized) return;
  searchInitialized = true;

  const input = document.getElementById("city-search-input");
  const list = document.getElementById("city-search-results");
  let activeIdx = -1;
  let matches = [];

  /** Show or hide the dropdown. */
  function showDropdown(show) {
    list.classList.toggle("visible", show);
    input.setAttribute("aria-expanded", String(show));
  }

  /** Render the current matches into the dropdown list. */
  function renderMatches() {
    list.innerHTML = "";
    activeIdx = -1;

    if (matches.length === 0) {
      showDropdown(false);
      return;
    }

    matches.forEach((entry, i) => {
      const li = document.createElement("li");
      li.setAttribute("role", "option");
      li.setAttribute("tabindex", "-1");
      li.id = `city-option-${i}`;
      li.textContent = entry.label;
      li.addEventListener("mousedown", (e) => {
        e.preventDefault(); // keep focus on input
        pickMatch(i);
      });
      li.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          pickMatch(i);
        } else if (e.key === "ArrowDown") {
          e.preventDefault();
          const next = Math.min(i + 1, matches.length - 1);
          setActive(next);
          list.children[next].focus();
        } else if (e.key === "ArrowUp") {
          e.preventDefault();
          if (i === 0) {
            input.focus();
          } else {
            setActive(i - 1);
            list.children[i - 1].focus();
          }
        } else if (e.key === "Escape") {
          showDropdown(false);
          input.focus();
        }
      });
      list.appendChild(li);
    });

    showDropdown(true);
  }

  /** Commit a selection by index. */
  function pickMatch(idx) {
    if (idx < 0 || idx >= matches.length) return;
    const entry = matches[idx];
    input.value = entry.label;
    showDropdown(false);
    selectCity(entry.city);
  }

  /** Set the visual active state for keyboard navigation. */
  function setActive(idx) {
    const items = list.querySelectorAll("li");
    items.forEach((li) => li.classList.remove("active"));
    activeIdx = idx;
    if (idx >= 0 && idx < items.length) {
      items[idx].classList.add("active");
      items[idx].scrollIntoView({ block: "nearest" });
      input.setAttribute("aria-activedescendant", items[idx].id);
    } else {
      input.removeAttribute("aria-activedescendant");
    }
  }

  input.addEventListener("input", () => {
    const query = input.value.trim().toLowerCase();
    if (query.length === 0) {
      matches = [];
      renderMatches();
      resetHighlights();
      return;
    }

    // Filter: prefer starts-with, then contains
    const startsWith = [];
    const contains = [];
    for (const entry of searchEntries) {
      const lower = entry.label.toLowerCase();
      if (lower.startsWith(query)) startsWith.push(entry);
      else if (lower.includes(query)) contains.push(entry);
    }
    matches = startsWith.concat(contains).slice(0, 15);
    renderMatches();
  });

  input.addEventListener("keydown", (e) => {
    if (!list.classList.contains("visible")) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive(Math.min(activeIdx + 1, matches.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive(Math.max(activeIdx - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (activeIdx >= 0) {
        pickMatch(activeIdx);
      } else if (matches.length > 0) {
        pickMatch(0);
      }
    } else if (e.key === "Escape") {
      showDropdown(false);
    } else if (e.key === "Tab" && list.classList.contains("visible")) {
      e.preventDefault();
      const target = activeIdx >= 0 ? activeIdx : 0;
      setActive(target);
      list.children[target].focus();
    }
  });

  // Close dropdown when clicking elsewhere
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#city-search")) {
      showDropdown(false);
    }
  });

  // Reset button: clear search, reset highlights, zoom to all cities
  document.getElementById("city-search-reset").addEventListener("click", () => {
    input.value = "";
    matches = [];
    showDropdown(false);
    resetHighlights();
    map.closePopup();
    if (allCityBounds) map.flyToBounds(allCityBounds, { duration: 1.2 });
  });
}

// ── Scatter plots ─────────────────────────────────────────────

/**
 * Create the two bottom-right scatter plots: pano count vs. age
 * and city area vs. age.
 *
 * @param {Object[]} cities - Array of city records.
 */
function createScatterPlots(cities) {
  // Cities without a median age have no y value to plot — they stay on
  // the map (greyed) but are omitted from the scatters.
  const datedCities = cities.filter(
    (c) => c.pano_age_stats.median_pano_age_years != null);

  const panoData = datedCities.map((city) => ({
    x: city.pano_count,
    y: city.pano_age_stats.median_pano_age_years,
    city,
    backgroundColor: getColor(city.pano_age_stats.median_pano_age_years, currentProvider),
  }));

  const areaData = datedCities.map((city) => ({
    x: city.search_area_km2,
    y: city.pano_age_stats.median_pano_age_years,
    city,
    backgroundColor: getColor(city.pano_age_stats.median_pano_age_years, currentProvider),
  }));

  const sharedOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      tooltip: {
        callbacks: {
          label: (ctx) => [
            getCityLabel(ctx.raw.city),
            `Age: ${ctx.raw.y.toFixed(1)} years`,
          ],
        },
      },
    },
    scales: {
      y: {
        beginAtZero: true,
        title: { display: true, text: "Median Age (years)" },
      },
    },
    onHover: (_event, elements) => {
      if (elements.length > 0) {
        highlightCity(elements[0].element.$context.raw.city);
      } else {
        resetHighlights();
      }
    },
    onClick: (_event, elements) => {
      if (elements.length === 0) return;
      const c = elements[0].element.$context.raw.city;
      const bounds = [
        [c.bounds.min_lat, c.bounds.min_lon],
        [c.bounds.max_lat, c.bounds.max_lon],
      ];
      const latSpan = c.bounds.max_lat - c.bounds.min_lat;
      const lonSpan = c.bounds.max_lon - c.bounds.min_lon;
      const padding = Math.max(latSpan, lonSpan) * 5.5;
      map.fitBounds([
        [bounds[0][0] - padding, bounds[0][1] - padding],
        [bounds[1][0] + padding, bounds[1][1] + padding],
      ]);
    },
  };

  charts.pano = new Chart(document.getElementById("panoScatter"), {
    type: "scatter",
    data: {
      datasets: [{
        data: panoData,
        backgroundColor: panoData.map((d) => d.backgroundColor),
        pointRadius: 4,
        pointHoverRadius: 7,
        borderColor: "rgba(0,0,0,0.2)",
        borderWidth: 1,
      }],
    },
    options: {
      ...sharedOptions,
      plugins: {
        ...sharedOptions.plugins,
        legend: { display: false },
        title: { display: true, text: "Pano Count vs Median Age" },
      },
      scales: {
        ...sharedOptions.scales,
        x: {
          // Auto-ranged: a fixed min of 100 hid every city with fewer
          // than 100 panos (small towns, sparse Mapillary coverage)
          type: "logarithmic",
          title: { display: true, text: "Total Panos (log scale)" },
        },
      },
    },
  });

  charts.area = new Chart(document.getElementById("areaScatter"), {
    type: "scatter",
    data: {
      datasets: [{
        data: areaData,
        backgroundColor: areaData.map((d) => d.backgroundColor),
        pointRadius: 4,
        pointHoverRadius: 7,
        borderColor: "rgba(0,0,0,0.2)",
        borderWidth: 1,
      }],
    },
    options: {
      ...sharedOptions,
      plugins: {
        ...sharedOptions.plugins,
        legend: { display: false },
        title: { display: true, text: "City Size (km²) vs Median Age" },
      },
      scales: {
        ...sharedOptions.scales,
        x: {
          // Auto-ranged (a fixed min of 1 hid sub-km² villages)
          type: "logarithmic",
          title: { display: true, text: "Area (km², log scale)" },
        },
      },
    },
  });
}

// ── Provider toggle & rendering ───────────────────────────────

/**
 * Render everything (banner, legend, rectangles, scatter plots, search)
 * for the current provider from the already-fetched payload.
 *
 * @param {boolean} [fitMap=false] - Fit the viewport to all cities
 *   (first render only; provider switches keep the current view).
 */
function renderProvider(fitMap = false) {
  const providerInfo = PROVIDERS[currentProvider];
  const { meta, cities } = adaptCitiesPayload(rawCitiesData, currentProvider);

  // Clear previous provider's view
  map.closePopup();
  mapRectangles.forEach((rect) => rect.remove());
  mapRectangles.length = 0;
  [charts.pano, charts.area].forEach((chart) => chart?.destroy());
  charts.pano = charts.area = null;

  // Provider attribution (Mapillary's terms require visible attribution)
  Object.values(PROVIDERS).forEach((p) =>
    map.attributionControl.removeAttribution(p.attribution));
  map.attributionControl.addAttribution(providerInfo.attribution);

  // Stats banner
  document.getElementById("stats").innerHTML = `
    <strong>${providerInfo.label} City Coverage Analysis</strong><br>
    ${cities.length} cities analyzed | Updated: ${new Date(meta.generatedAt).toLocaleString()}
  `;

  if (cities.length === 0) {
    document.getElementById("legend").innerHTML =
      `<h4>No ${providerInfo.label} data yet</h4>`;
    return;
  }

  // Legend
  const maxAge = Math.max(
    ...cities.map((c) => c.pano_age_stats.median_pano_age_years || 0)
  );
  createLegend(maxAge, cities);

  // Map rectangles
  cities.forEach((city) => {
    const bounds = [
      [city.bounds.min_lat, city.bounds.min_lon],
      [city.bounds.max_lat, city.bounds.max_lon],
    ];

    const median = city.pano_age_stats.median_pano_age_years;
    const rect = L.rectangle(bounds, {
      color: median != null ? getColor(median, currentProvider) : NO_DATA_COLOR,
      weight: 1,
      fillOpacity: 0.6,
    }).addTo(map);

    rect.city = city;
    // Content function: the popup DOM (including its Chart.js histogram)
    // is built on OPEN, not eagerly for all ~1,100 cities at render time —
    // and rebuilt each open, so a provider toggle can't leak stale charts.
    rect.bindPopup(() => createTooltip(city));
    mapRectangles.push(rect);

    rect.on("mouseover", () => highlightCity(city));
    rect.on("mouseout", () => resetHighlights());
  });

  createScatterPlots(cities);
  initCitySearch(cities);

  allCityBounds = cities.map((c) => [
    [c.bounds.min_lat, c.bounds.min_lon],
    [c.bounds.max_lat, c.bounds.max_lon],
  ]);
  if (fitMap) map.fitBounds(allCityBounds);
}

/**
 * Switch the active imagery provider, re-render from the cached payload,
 * and persist the choice in the URL.
 *
 * @param {string} provider - Provider key (see PROVIDERS).
 */
function setProvider(provider) {
  if (!isKnownProvider(provider) || provider === currentProvider) return;
  currentProvider = provider;

  const url = new URL(window.location);
  if (provider === "gsv") url.searchParams.delete("provider");
  else url.searchParams.set("provider", provider);
  history.replaceState(null, "", url);

  // Before the payload arrives, just record the choice — the initial
  // renderProvider(true) in loadData() picks it up. (Previously a click
  // during the fetch was silently reverted.)
  if (rawCitiesData) renderProvider();
}

/** Wire up the provider radio group and reflect the initial state. */
function initProviderToggle() {
  document.querySelectorAll('input[name="provider"]').forEach((radio) => {
    radio.checked = radio.value === currentProvider;
    radio.addEventListener("change", () => {
      if (radio.checked) setProvider(radio.value);
    });
  });
}

// ── Data loading ──────────────────────────────────────────────

/** Fetch cities.json.gz, then render the active provider's view. */
async function loadData() {
  // Wire the toggle BEFORE the fetch so a click during loading is
  // recorded (setProvider defers the render until data arrives).
  initProviderToggle();
  try {
    rawCitiesData = await fetchGzippedJson(STREETSCAPE_DATA_BASE_URL + "cities.json.gz");
    document.getElementById("loading").style.display = "none";
    renderProvider(true);
  } catch (error) {
    console.error("Error loading data:", error);
    document.getElementById("loading").textContent =
      "Error loading city data. Please check the console for details.";
  }
}

document.addEventListener("DOMContentLoaded", loadData);