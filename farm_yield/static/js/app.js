(function () {
  const appRoot = document.querySelector(".app");
  const submittedLat = appRoot?.dataset.submittedLat;
  const submittedLon = appRoot?.dataset.submittedLon;

  const INDIA_LIMITS = {
    minLat: 6.0,
    maxLat: 38.5,
    minLon: 67.0,
    maxLon: 98.5
  };

  const INDIA_MAINLAND_POLYGON = [
    [23.5, 68.0], [24.8, 68.7], [26.6, 69.4], [29.0, 70.2], [31.8, 74.2],
    [34.2, 75.5], [35.8, 77.4], [35.8, 79.8], [34.0, 78.6], [31.8, 78.0],
    [30.1, 79.0], [28.2, 80.6], [27.0, 82.8], [26.1, 84.6], [25.7, 86.8],
    [25.5, 88.5], [24.5, 89.5], [23.0, 89.9], [21.7, 89.5], [20.6, 88.8],
    [21.0, 87.2], [20.7, 86.0], [19.7, 85.0], [19.0, 83.8], [18.3, 82.8],
    [17.3, 81.5], [16.1, 80.5], [15.0, 80.3], [13.5, 80.2], [12.1, 79.8],
    [10.8, 79.2], [9.1, 78.8], [8.1, 77.6], [8.2, 76.2], [9.2, 75.4],
    [10.6, 74.8], [12.2, 74.3], [13.8, 74.0], [15.2, 73.8], [17.0, 73.4],
    [18.6, 72.9], [20.0, 72.2], [21.1, 71.5], [22.0, 70.6], [22.8, 69.6],
    [23.3, 68.8]
  ];

  const INDIA_NORTHEAST_POLYGON = [
    [22.0, 88.0], [23.0, 88.6], [24.2, 89.8], [25.4, 90.8], [26.6, 91.8],
    [27.6, 92.8], [28.7, 94.0], [29.4, 95.2], [29.6, 96.6], [29.1, 97.6],
    [28.0, 97.9], [26.8, 97.6], [25.8, 96.9], [24.8, 96.0], [24.0, 95.0],
    [23.4, 94.0], [22.8, 93.0], [22.4, 92.0], [22.1, 90.8], [22.0, 89.2]
  ];

  const INDIA_ISLAND_BOXES = [
    { minLat: 6.0, maxLat: 14.5, minLon: 92.0, maxLon: 94.5 },
    { minLat: 8.0, maxLat: 13.8, minLon: 72.0, maxLon: 74.0 }
  ];

  let selectedCrop = "Wheat";
  let currentPin = null;
  let analysisGeneration = 0;
  let analysisController = null;
  let loadingInterval = null;
  let drawing = false;
  let outlinePoints = [];
  let outlineLayer = null;
  let districtLayer = null;
  let layerGeneration = 0;

  const indiaBounds = L.latLngBounds(
    [INDIA_LIMITS.minLat, INDIA_LIMITS.minLon],
    [INDIA_LIMITS.maxLat, INDIA_LIMITS.maxLon]
  );

  const map = L.map("farm-map", {
    zoomControl: false,
    scrollWheelZoom: true,
    minZoom: 4,
    maxZoom: 17,
    maxBounds: indiaBounds,
    maxBoundsViscosity: 1.0
  });

  L.control.zoom({ position: "topright" }).addTo(map);
  map.fitBounds(indiaBounds);

  const primaryTiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
    maxZoom: 19,
    noWrap: true
  }).addTo(map);

  primaryTiles.on("tileerror", function () {
    document.getElementById("map-tool-status").textContent = "Base map tiles could not be loaded. Check your connection before drawing a field.";
  });

  const pinIcon = L.divIcon({
    className: "",
    html: '<div class="farm-pin"></div>',
    iconSize: [18, 18],
    iconAnchor: [9, 9]
  });

  function pointInPolygon(lat, lon, polygon) {
    let inside = false;
    let j = polygon.length - 1;

    for (let i = 0; i < polygon.length; i += 1) {
      const yi = polygon[i][0];
      const xi = polygon[i][1];
      const yj = polygon[j][0];
      const xj = polygon[j][1];

      const intersects = ((xi > lon) !== (xj > lon)) &&
        (lat < ((yj - yi) * (lon - xi)) / ((xj - xi) || 1e-12) + yi);

      if (intersects) {
        inside = !inside;
      }
      j = i;
    }

    return inside;
  }

  function isWithinIndia(lat, lon) {
    const withinBounds = (
      lat >= INDIA_LIMITS.minLat &&
      lat <= INDIA_LIMITS.maxLat &&
      lon >= INDIA_LIMITS.minLon &&
      lon <= INDIA_LIMITS.maxLon
    );

    if (!withinBounds) {
      return false;
    }

    if (pointInPolygon(lat, lon, INDIA_MAINLAND_POLYGON)) {
      return true;
    }

    if (pointInPolygon(lat, lon, INDIA_NORTHEAST_POLYGON)) {
      return true;
    }

    return INDIA_ISLAND_BOXES.some(function (box) {
      return (
        lat >= box.minLat &&
        lat <= box.maxLat &&
        lon >= box.minLon &&
        lon <= box.maxLon
      );
    });
  }

  function setCoords(lat, lon) {
    document.getElementById("lat-input").value = lat;
    document.getElementById("lon-input").value = lon;
    document.getElementById("lat-display").textContent = lat.toFixed(5);
    document.getElementById("lon-display").textContent = lon.toFixed(5);
    document.getElementById("pin-coords").textContent = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
    document.getElementById("pin-status").textContent = "Farm pin locked. You can move it anytime by clicking another point on the map.";
  }

  function showIndiaMessage() {
    alert("Please select a location in India.");
  }

  function placePin(lat, lon, zoomLevel = 12, animate = false) {
    if (!isWithinIndia(lat, lon)) {
      showIndiaMessage();
      return false;
    }

    if (currentPin) {
      map.removeLayer(currentPin);
    }

    currentPin = L.marker([lat, lon], { icon: pinIcon }).addTo(map);
    setCoords(lat, lon);
    document.getElementById("analyze-btn").disabled = false;
    clearResults();

    if (animate) {
      map.flyTo([lat, lon], zoomLevel, { duration: 1.2 });
    } else {
      map.setView([lat, lon], zoomLevel);
    }

    return true;
  }

  map.on("click", function (event) {
    if (drawing) {
      if (!isWithinIndia(event.latlng.lat, event.latlng.lng)) return;
      outlinePoints.push([event.latlng.lat, event.latlng.lng]);
      if (outlineLayer) map.removeLayer(outlineLayer);
      outlineLayer = L.polygon(outlinePoints, {color: "#8a5d12"}).addTo(map);
      document.getElementById("finish-outline").disabled = outlinePoints.length < 3;
      document.getElementById("map-tool-status").textContent = `${outlinePoints.length} outline vertices; click Finish outline when ready.`;
      return;
    }
    placePin(event.latlng.lat, event.latlng.lng, Math.max(map.getZoom(), 12), false);
  });

  if (submittedLat && submittedLon) {
    placePin(parseFloat(submittedLat), parseFloat(submittedLon), 12, false);
  }

  document.querySelectorAll(".overlay-close").forEach(function (button) {
    button.addEventListener("click", function () {
      const card = this.closest("[data-overlay]");
      if (card) {
        card.style.display = "none";
      }
    });
  });

  document.getElementById("search-btn").addEventListener("click", doSearch);
  document.getElementById("location-search").addEventListener("keydown", function (event) {
    if (event.key === "Enter") {
      doSearch();
    }
  });

  function doSearch() {
    const query = document.getElementById("location-search").value.trim();
    if (!query) return;

    const searchButton = document.getElementById("search-btn");
    searchButton.disabled = true;
    searchButton.textContent = "Searching...";

    fetch(`https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&countrycodes=in`)
      .then(response => response.json())
      .then(data => {
        if (!data.length) {
          alert("Location not found. Try adding a nearby village, district, or state name.");
          return;
        }

        const lat = parseFloat(data[0].lat);
        const lon = parseFloat(data[0].lon);

        if (!isWithinIndia(lat, lon)) {
          showIndiaMessage();
          return;
        }

        placePin(lat, lon, 12, true);
      })
      .catch(() => {
        alert("Search failed. Please try again in a moment.");
      })
      .finally(() => {
        searchButton.disabled = false;
        searchButton.textContent = "Search";
      });
  }

  document.querySelectorAll(".crop-btn").forEach(function (button) {
    button.addEventListener("click", function () {
      document.querySelectorAll(".crop-btn").forEach(function (item) {
        item.classList.remove("active");
      });
      this.classList.add("active");
      selectedCrop = this.dataset.crop;
      clearResults();
    });
  });

  document.getElementById("analyze-btn").addEventListener("click", runAnalysis);

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = String(text);
    return node;
  }

  function runAnalysis() {
    const lat = document.getElementById("lat-input").value;
    const lon = document.getElementById("lon-input").value;
    if (!lat || !lon) return;
    clearResults();
    const generation = analysisGeneration;
    const controller = new AbortController();
    analysisController = controller;
    showLoading();
    const timeout = setTimeout(() => controller.abort(), 180000);
    fetch("/api/fetch_ndvi", {
      method: "POST", headers: {"Content-Type": "application/json"},
      signal: controller.signal, body: JSON.stringify({lat, lon, crop: selectedCrop})
    }).then(async response => {
      const data = await response.json();
      if (!response.ok) throw data;
      return data;
    }).then(data => {
      if (generation !== analysisGeneration) return;
      renderResults(data);
      loadHistory();
    }).catch(error => {
      if (generation !== analysisGeneration) return;
      renderResults({error: error.name === "AbortError" ? "Analysis timed out. Please try again." : (error.error || "Analysis could not be completed.")});
    }).finally(() => {
      clearTimeout(timeout);
      if (generation === analysisGeneration) hideLoading();
    });
  }

  function renderResults(data) {
    const container = document.getElementById("result-cards");
    container.replaceChildren();
    container.style.display = "grid";
    document.getElementById("empty-state").style.display = "none";
    if (data.error) {
      const card = element("div", "message-card");
      card.style.gridColumn = "1 / -1";
      card.append(element("h4", "", "Unable to complete analysis"), element("p", "", data.error));
      container.append(card);
      return;
    }
    const prediction = element("article", "result-card");
    prediction.append(element("div", "result-kicker", "Completed-season district research estimate"),
      element("div", "prediction-value", `${data.prediction} t/ha`));
    const tags = element("div", "tag-row");
    [data.crop, data.season, data.model].forEach(text => tags.append(element("div", "tag", text)));
    prediction.append(tags);
    container.append(prediction);
    const vegetation = element("article", "result-card");
    vegetation.append(element("div", "result-kicker", "Observed vegetation signal"),
      element("div", "ndvi-value", data.ndvi == null ? "Unavailable" : Number(data.ndvi).toFixed(4)),
      element("p", "", "NDVI describes vegetation; it is not a diagnosis of field health."));
    container.append(vegetation);
    if (data.weather) {
      const card = element("article", "result-card wide");
      card.append(element("div", "result-kicker", "Completed-season weather"));
      const grid = element("div", "metric-grid");
      [["Average temperature", `${data.weather.temp} °C`], ["Rainfall", `${data.weather.rainfall} mm`],
       ["Humidity", `${data.weather.humidity} %`], ["Root soil wetness", `${data.weather.soil} %`]].forEach(([name, value]) => {
        const item = element("div", "metric");
        item.append(element("span", "", name), element("strong", "", value));
        grid.append(item);
      });
      card.append(grid);
      container.append(card);
    }
    const evidence = element("article", "result-card wide");
    evidence.append(element("div", "result-kicker", "Provenance and limits"),
      element("p", "", `Prediction ${data.prediction_id} · Model ${data.model_version}`),
      element("p", "", `${data.season_window?.start} to ${data.season_window?.end} · ${data.evaluation_unit} evaluation`));
    evidence.append(element("p", "", `${data.district || "District"} · ${data.observation_source || "Verified historical observations"}`));
    if (data.satellite_temporal_support) evidence.append(element("p", "", `Satellite composite support may extend through ${data.satellite_temporal_support.latest_possible_end}.`));
    Object.entries(data.feature_availability || {}).forEach(([name, count]) => evidence.append(element("p", "", `${name}: ${count} season months available`)));
    (data.alerts || []).forEach(alert => evidence.append(element("p", "", alert.message)));
    (data.evidence_limits || []).forEach(limit => evidence.append(element("p", "", limit)));
    container.append(evidence);
  }

  async function loadHistory() {
    const status = document.getElementById("history-status");
    const list = document.getElementById("prediction-history");
    try {
      const response = await fetch("/api/predictions", {cache: "no-store"});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      list.replaceChildren();
      (data.predictions || []).forEach(item => {
        const button = element("button", "history-entry", `${item.crop} · ${item.harvest_year} · ${item.prediction} t/ha`);
        button.type = "button";
        button.addEventListener("click", () => {clearResults(); renderResults(item);});
        list.append(button);
      });
      status.textContent = data.predictions.length ? "Latest 20 predictions in this signed browser session." : "No saved predictions in this browser session.";
    } catch (error) {
      list.replaceChildren();
      status.textContent = "History unavailable: " + error.message;
    }
  }
  document.getElementById("refresh-history").addEventListener("click", loadHistory);
  loadHistory();

  const toolStatus = document.getElementById("map-tool-status");
  document.getElementById("draw-outline").addEventListener("click", () => {
    layerGeneration += 1;
    if (districtLayer) {map.removeLayer(districtLayer); districtLayer = null;}
    document.getElementById("district-layer").disabled = true;
    drawing = true;
    outlinePoints = [];
    if (outlineLayer) map.removeLayer(outlineLayer);
    document.getElementById("export-outline").disabled = true;
    document.getElementById("finish-outline").disabled = true;
    toolStatus.textContent = "Click at least three field corners on the map, then Finish outline. This does not change prediction evidence.";
  });
  document.getElementById("finish-outline").addEventListener("click", () => {
    if (outlinePoints.length < 3) return;
    drawing = false;
    document.getElementById("district-layer").disabled = false;
    document.getElementById("finish-outline").disabled = true;
    document.getElementById("export-outline").disabled = false;
    toolStatus.textContent = "Field outline ready to export. Its yield accuracy has not been validated.";
  });
  document.getElementById("clear-outline").addEventListener("click", () => {
    drawing = false;
    document.getElementById("district-layer").disabled = false;
    outlinePoints = [];
    if (outlineLayer) map.removeLayer(outlineLayer);
    outlineLayer = null;
    document.getElementById("finish-outline").disabled = true;
    document.getElementById("export-outline").disabled = true;
    toolStatus.textContent = "Field outline cleared.";
  });
  document.getElementById("export-outline").addEventListener("click", () => {
    if (drawing || outlinePoints.length < 3) return;
    const ring = outlinePoints.map(([lat, lon]) => [lon, lat]);
    ring.push([...ring[0]]);
    const feature = {type: "Feature", properties: {purpose: "user-drawn field outline", evidence: "District labels do not validate field-level accuracy."}, geometry: {type: "Polygon", coordinates: [ring]}};
    const url = URL.createObjectURL(new Blob([JSON.stringify(feature)], {type: "application/geo+json"}));
    const link = element("a");
    link.href = url;
    link.download = "field-outline.geojson";
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  document.getElementById("district-layer").addEventListener("click", async () => {
    const generation = ++layerGeneration;
    const crop = selectedCrop;
    if (districtLayer) {map.removeLayer(districtLayer); districtLayer = null;}
    toolStatus.textContent = `Loading ${crop} district backtest...`;
    try {
      const response = await fetch(`/api/yield-map?crop=${encodeURIComponent(crop)}`);
      const data = await response.json();
      if (generation !== layerGeneration) return;
      if (!response.ok) throw new Error(data.error);
      districtLayer = L.geoJSON(data, {attribution: 'Districts: geoBoundaries / Pathways Data / LG Directory (ODbL 1.0)',
        style: feature => ({color: "#17623c", weight: 1, fillOpacity: .45,
        fillColor: feature.properties.prediction_t_ha > 3 ? "#14733e" : "#b9d9a8"}),
        onEachFeature: (feature, layer) => {
          const p = feature.properties;
          layer.bindPopup(element("p", "", `${p.district}: ${p.prediction_t_ha.toFixed(2)} t/ha, observed ${p.observed_t_ha.toFixed(2)}. ${p.harvest_year} district retrospective backtest.`));
        }}).addTo(map);
      toolStatus.textContent = `${data.features.length} ${crop} districts: 2019 retrospective backtest. Outlines remain separate user drawings.`;
    } catch (error) {
      if (generation === layerGeneration) toolStatus.textContent = error.message;
    }
  });

  function showLoading() {
    document.getElementById("empty-state").style.display = "none";
    document.getElementById("result-cards").style.display = "none";
    document.getElementById("loading-state").classList.add("show");
    document.getElementById("loading-msg").textContent = "Preparing satellite and climate inputs...";
    document.getElementById("analyze-btn").disabled = true;
  }

  function hideLoading() {
    document.getElementById("loading-state").classList.remove("show");
    document.getElementById("analyze-btn").disabled = false;
  }

  function clearResults() {
    analysisGeneration += 1;
    if (analysisController) analysisController.abort();
    clearInterval(loadingInterval);
    layerGeneration += 1;
    if (districtLayer) {map.removeLayer(districtLayer); districtLayer = null;}
    document.getElementById("analyze-btn").disabled = !currentPin;
    document.getElementById("result-cards").style.display = "none";
    document.getElementById("result-cards").innerHTML = "";
    document.getElementById("empty-state").style.display = "block";
    document.getElementById("loading-state").classList.remove("show");
  }

  window.addEventListener("load", function () {
    setTimeout(function () {
      map.invalidateSize();
    }, 150);
  });

  window.addEventListener("resize", function () {
    map.invalidateSize();
  });
})();
