/**
 * index.js
 * Overview-map logic for GSV City Explorer.
 *
 * Depends on globals from gsv-utils.js (getColor, fetchGzippedJson,
 * GSV_DATA_BASE_URL) and the Leaflet / Chart.js libraries.
 */

// ── Global state ──────────────────────────────────────────────
const map = L.map("map").setView([0, 0], 2);
const charts = { pano: null, area: null };
const mapRectangles = [];
let allCityBounds = null;

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
  const years = Object.keys(histogramData).map(Number).sort((a, b) => a - b);
  const counts = years.map((y) => histogramData[y]);
  const ages = years.map((y) => currentYear - y);

  new Chart(canvas, {
    type: "bar",
    data: {
      labels: years,
      datasets: [{
        data: counts,
        backgroundColor: ages.map((a) => getColor(a)),
        borderColor: "rgba(0,0,0,0.2)",
        borderWidth: 1,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        title: { display: true, text: "Google Panoramas by Capture Year" },
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
  const cityName = city.city || city.state;
  const container = document.createElement("div");
  container.style.minWidth = "250px";

  const panoStats = city.panorama_counts;
  const ageStats = city.google_panos_age_stats;
  const googlePct = ((panoStats.unique_google_panos / panoStats.unique_panos) * 100).toFixed(1);

  container.innerHTML = `
    <h3>${cityName}, ${city.state.name}, ${city.country.name}</h3>
    <strong>Coverage Statistics:</strong>
    <ul class="popup-stats-list">
      <li>Data Collected: ${city.collection_info?.end_time ? new Date(city.collection_info.end_time).toLocaleDateString() : "Unknown"}</li>
      <li>Area: ${city.search_area_km2.toFixed(1)} km²</li>
      <li>Total Panoramas: ${panoStats.unique_panos.toLocaleString()}</li>
      <li>Google Panoramas: ${panoStats.unique_google_panos.toLocaleString()} (${googlePct}%)</li>
    </ul>
    <div style="margin-top:12px"><strong>Age Statistics:</strong></div>
    <ul class="popup-stats-list">
      <li>Median Age: ${ageStats.median_pano_age_years ? ageStats.median_pano_age_years.toFixed(1) + " years" : "No data"}</li>
      <li>Average Age: ${ageStats.avg_pano_age_years ? ageStats.avg_pano_age_years.toFixed(1) + " years" : "No data"}
        ${ageStats.stdev_pano_age_years ? ` (SD=${ageStats.stdev_pano_age_years.toFixed(1)})` : ""}</li>
      <li>Newest: ${ageStats.newest_pano_date ? new Date(ageStats.newest_pano_date).toLocaleDateString() : "No data"}</li>
      <li>Oldest: ${ageStats.oldest_pano_date ? new Date(ageStats.oldest_pano_date).toLocaleDateString() : "No data"}</li>
    </ul>
  `;

  // Histogram chart
  const chartContainer = document.createElement("div");
  chartContainer.className = "popup-chart-container";

  const currentYear = new Date().getFullYear();
  const rawHistogram =
    city.histogram_of_capture_dates_by_year.google_panos.counts ||
    city.histogram_of_capture_dates_by_year.google_panos;

  const years = Object.keys(rawHistogram).map(Number);
  const startYear = Math.min(...years);
  const filledHistogram = {};
  for (let y = startYear; y <= currentYear; y++) {
    filledHistogram[y] = rawHistogram[y] || 0;
  }

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
 * Populate the legend panel with one row per integer-age bucket.
 *
 * @param {number} maxAge - Maximum median age across all cities.
 * @param {Object[]} cities - Array of city records.
 */
/**
 * Populate the legend panel with one row per integer-age bucket.
 */
function createLegend(maxAge, cities) {
  const legend = document.getElementById("legend");
  const maxYears = Math.ceil(maxAge);

  const ageCounts = new Array(maxYears + 1).fill(0);
  cities.forEach((city) => {
    const age = Math.floor(city.google_panos_age_stats.median_pano_age_years);
    if (age <= maxYears) ageCounts[age]++;
  });

  let html = "<h4>Median Age (years)</h4>";
  for (let age = 0; age <= maxYears; age++) {
    const color = getColor(age);
    const n = ageCounts[age];
    const label = n > 0 ? `(${n} ${n === 1 ? "city" : "cities"})` : "(no cities)";

    html += `
      <div class="legend-item" role="listitem" tabindex="0"
           data-age="${age}" aria-label="${age} years, ${label}">
        <div class="legend-color" style="background:${color}" aria-hidden="true"></div>
        ${age} year${age !== 1 ? "s" : ""} ${label}
      </div>`;
  }
  legend.innerHTML = html;

  // Click & keyboard handlers
  legend.querySelectorAll(".legend-item").forEach((item) => {
    const handler = () => {
      const isAlreadySelected = item.classList.contains("selected");
      
      // Clear selection from all items
      legend.querySelectorAll(".legend-item").forEach(i => i.classList.remove("selected"));

      if (isAlreadySelected) {
        resetHighlights();
      } else {
        item.classList.add("selected");
        highlightCitiesByExactAge(parseInt(item.dataset.age, 10));
      }
    };

    item.addEventListener("click", handler);
    item.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        handler();
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
function highlightCitiesByExactAge(targetAge, zoomToHighlightedCities = false) {
  const tolerance = 0.5;

  [charts.pano, charts.area].forEach((chart) => {
    const ds = chart.data.datasets[0];
    ds.pointBackgroundColor = ds.data.map((pt) => {
      const age = Math.floor(pt.y);
      return Math.abs(age - targetAge) <= tolerance
        ? pt.backgroundColor
        : pt.backgroundColor.replace("rgb", "rgba").replace(")", ",0.3)");
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

  const highlightedCities = [];
  mapRectangles.forEach((rect) => {
    const age = Math.floor(rect.city.google_panos_age_stats.median_pano_age_years);
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

  if (highlightedCities.length > 0 && zoomToHighlightedCities) {
    const minLat = Math.min(...highlightedCities.map((c) => c.bounds.min_lat));
    const maxLat = Math.max(...highlightedCities.map((c) => c.bounds.max_lat));
    const minLon = Math.min(...highlightedCities.map((c) => c.bounds.min_lon));
    const maxLon = Math.max(...highlightedCities.map((c) => c.bounds.max_lon));
    const latPad = (maxLat - minLat) * 0.2;
    const lonPad = (maxLon - minLon) * 0.2;
    map.fitBounds([
      [minLat - latPad, minLon - lonPad],
      [maxLat + latPad, maxLon + lonPad],
    ]);
  }
}

/**
 * Highlight cities whose median age falls in [minAge, maxAge).
 *
 * @param {number} minAge
 * @param {number} maxAge
 */
function highlightCitiesByAgeRange(minAge, maxAge) {
  [charts.pano, charts.area].forEach((chart) => {
    chart.data.datasets[0].pointBackgroundColor = chart.data.datasets[0].data.map((pt) =>
      pt.y >= minAge && pt.y < maxAge ? pt.backgroundColor : "rgba(200,200,200,0.2)"
    );
    chart.update();
  });

  mapRectangles.forEach((rect) => {
    const age = rect.city.google_panos_age_stats.median_pano_age_years;
    rect.setStyle(age >= minAge && age < maxAge
      ? { fillOpacity: 0.8, weight: 2 }
      : { fillOpacity: 0.2, weight: 1 });
  });
}

/**
 * Highlight a single city across both scatter charts and the map.
 *
 * @param {Object} city - The city record to highlight.
 */
function highlightCity(city) {
  [charts.pano, charts.area].forEach((chart) => {
    const ds = chart.data.datasets[0];
    ds.pointBackgroundColor = ds.data.map((pt) =>
      pt.city === city
        ? pt.backgroundColor
        : pt.backgroundColor.replace("rgb", "rgba").replace(")", ",0.3)")
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
  const name = city.city || city.state?.name || city.country.name;
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

/**
 * Initialise the city search autocomplete once city data is loaded.
 * @param {Object[]} cities - Array of city records.
 */
function initCitySearch(cities) {
  const input = document.getElementById("city-search-input");
  const list = document.getElementById("city-search-results");
  let activeIdx = -1;
  let matches = [];

  // Pre-compute labels and sort alphabetically
  const entries = cities
    .map((city) => ({ city, label: getCityLabel(city) }))
    .sort((a, b) => a.label.localeCompare(b.label));

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
    for (const entry of entries) {
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
  const panoData = cities.map((city) => ({
    x: city.panorama_counts.unique_google_panos,
    y: city.google_panos_age_stats.median_pano_age_years,
    city,
    backgroundColor: getColor(city.google_panos_age_stats.median_pano_age_years),
  }));

  const areaData = cities.map((city) => ({
    x: city.search_area_km2,
    y: city.google_panos_age_stats.median_pano_age_years,
    city,
    backgroundColor: getColor(city.google_panos_age_stats.median_pano_age_years),
  }));

  const sharedOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      tooltip: {
        callbacks: {
          label: (ctx) => {
            const c = ctx.raw.city;
            const name = c.city || c.state?.name || c.country.name;
            const loc = c.state?.name
              ? `${name}, ${c.state.name}`
              : `${name}, ${c.country.name}`;
            return [loc, `Age: ${ctx.raw.y.toFixed(1)} years`];
          },
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
          type: "logarithmic",
          title: { display: true, text: "Total Panos (log scale)" },
          min: 100,
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
          type: "logarithmic",
          title: { display: true, text: "Area (km², log scale)" },
          min: 1,
        },
      },
    },
  });
}

// ── Data loading ──────────────────────────────────────────────

/** Fetch cities.json.gz, build the map, legend, and scatter plots. */
async function loadData() {
  try {
    const data = await fetchGzippedJson(GSV_DATA_BASE_URL + "cities.json.gz");

    if (!data?.cities || !Array.isArray(data.cities)) {
      throw new Error("Invalid data format: missing cities array");
    }

    const cities = data.cities;

    // Stats banner
    document.getElementById("stats").innerHTML = `
      <strong>GSV City Coverage Analysis</strong><br>
      ${data.cities_count} cities analyzed | Updated: ${new Date(data.creation_timestamp).toLocaleString()}
    `;

    document.getElementById("loading").style.display = "none";

    // Legend
    const maxAge = Math.max(
      ...cities.map((c) => c.google_panos_age_stats.median_pano_age_years)
    );
    createLegend(maxAge, cities);

    // Map rectangles
    cities.forEach((city) => {
      const bounds = [
        [city.bounds.min_lat, city.bounds.min_lon],
        [city.bounds.max_lat, city.bounds.max_lon],
      ];

      const rect = L.rectangle(bounds, {
        color: getColor(city.google_panos_age_stats.median_pano_age_years),
        weight: 1,
        fillOpacity: 0.6,
      }).addTo(map);

      rect.city = city;
      rect.bindPopup(createTooltip(city));
      mapRectangles.push(rect);

      rect.on("mouseover", () => highlightCity(city));
      rect.on("mouseout", () => resetHighlights());
    });

    createScatterPlots(cities);
    initCitySearch(cities);

    // Fit map to all cities
    allCityBounds = cities.map((c) => [
      [c.bounds.min_lat, c.bounds.min_lon],
      [c.bounds.max_lat, c.bounds.max_lon],
    ]);
    map.fitBounds(allCityBounds);
  } catch (error) {
    console.error("Error loading data:", error);
    document.getElementById("loading").textContent =
      "Error loading city data. Please check the console for details.";
  }
}

document.addEventListener("DOMContentLoaded", loadData);