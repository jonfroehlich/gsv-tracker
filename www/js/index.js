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
      <li>Area: ${city.search_area_km2.toFixed(1)} km²</li>
      <li>Total Panoramas: ${panoStats.unique_panos.toLocaleString()}</li>
      <li>Google Panoramas: ${panoStats.unique_google_panos.toLocaleString()} (${googlePct}%)</li>
    </ul>
    <div style="margin-top:12px"><strong>Age Statistics:</strong></div>
    <ul class="popup-stats-list">
      <li>Median Age: ${ageStats.median_pano_age_years ? ageStats.median_pano_age_years.toFixed(1) + " years" : "No data"}</li>
      <li>Average Age: ${ageStats.avg_pano_age_years ? ageStats.avg_pano_age_years.toFixed(1) + " years" : "No data"}
        ${ageStats.stdev_pano_age_years ? ` (SD=${ageStats.stdev_pano_age_years.toFixed(1)})` : ""}</li>
      <li>Newest: ${ageStats.newest_date ? new Date(ageStats.newest_date).toLocaleDateString() : "No data"}</li>
      <li>Oldest: ${ageStats.oldest_date ? new Date(ageStats.oldest_date).toLocaleDateString() : "No data"}</li>
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
    const label = n > 0
      ? `(${n} ${n === 1 ? "city" : "cities"})`
      : "(no cities)";

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
    const handler = () => highlightCitiesByExactAge(parseInt(item.dataset.age, 10));
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
      rect.setStyle({ fillOpacity: 0.8, weight: 2 });
      highlightedCities.push(rect.city);
    } else {
      rect.setStyle({ fillOpacity: 0.2, weight: 0.25 });
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

    // Fit map to all cities
    const allBounds = cities.map((c) => [
      [c.bounds.min_lat, c.bounds.min_lon],
      [c.bounds.max_lat, c.bounds.max_lon],
    ]);
    map.fitBounds(allBounds);
  } catch (error) {
    console.error("Error loading data:", error);
    document.getElementById("loading").textContent =
      "Error loading city data. Please check the console for details.";
  }
}

document.addEventListener("DOMContentLoaded", loadData);
