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

  let selectedCrop = "Sugarcane";
  let currentPin = null;
  let fallbackTilesLoaded = false;

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

  const primaryTiles = L.tileLayer("https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png", {
    attribution: "&copy; OpenStreetMap &copy; CARTO",
    subdomains: "abcd",
    maxZoom: 20,
    noWrap: true
  }).addTo(map);

  primaryTiles.on("tileerror", function () {
    if (fallbackTilesLoaded) return;
    fallbackTilesLoaded = true;
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: "&copy; OpenStreetMap contributors",
      maxZoom: 19,
      noWrap: true
    }).addTo(map);
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

  function runAnalysis() {
    const lat = document.getElementById("lat-input").value;
    const lon = document.getElementById("lon-input").value;
    if (!lat || !lon) return;

    showLoading();

    const messages = [
      "Fetching satellite vegetation data...",
      "Pulling seasonal weather from NASA POWER...",
      "Building crop-season features...",
      "Running the yield prediction model..."
    ];

    let index = 0;
    const intervalId = setInterval(function () {
      index = (index + 1) % messages.length;
      const loadingElement = document.getElementById("loading-msg");
      if (loadingElement) {
        loadingElement.textContent = messages[index];
      }
    }, 1900);

    fetch("/api/fetch_ndvi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ lat, lon, crop: selectedCrop })
    })
      .then(async function (response) {
        const data = await response.json();
        if (!response.ok) {
          throw data;
        }
        return data;
      })
      .then(function (data) {
        clearInterval(intervalId);
        hideLoading();
        renderResults(data);
      })
      .catch(function (error) {
        clearInterval(intervalId);
        hideLoading();
        renderResults(error && typeof error === "object" ? error : { error: "Analysis failed. Please try again." });
      });
  }

  function renderResults(data) {
    const container = document.getElementById("result-cards");
    container.innerHTML = "";
    container.style.display = "grid";

    if (data.status === "not_started") {
      container.innerHTML = '<div class="message-card" style="grid-column: 1 / -1;"><h4>Season not started</h4><p>' + data.message + "</p></div>";
      return;
    }

    if (data.status === "data_pending") {
      container.innerHTML = '<div class="message-card" style="grid-column: 1 / -1;"><h4>Weather data pending</h4><p>' + data.message + "</p></div>";
      return;
    }

    if (data.error) {
      container.innerHTML = '<div class="message-card" style="grid-column: 1 / -1; border-color: rgba(198, 79, 79, 0.24); background: linear-gradient(180deg, rgba(255, 246, 246, 0.98), rgba(255, 255, 255, 0.96));"><h4 style="color: var(--red);">Unable to complete analysis</h4><p>' + data.error + "</p></div>";
      return;
    }

    const tags = [
      data.crop,
      data.season,
      data.season_status ? data.season_status.replace("_", " ").toUpperCase() : null,
      data.model || null
    ]
      .filter(Boolean)
      .map(function (tag) {
        return '<div class="tag">' + tag + "</div>";
      })
      .join("");

    container.innerHTML += '<article class="result-card"><div class="result-kicker">Predicted Yield</div><div class="prediction-row"><div class="prediction-value">' + (data.prediction ?? "--") + '</div><div class="prediction-unit">T / Ha</div></div><div class="tag-row">' + tags + "</div></article>";

    if (data.ndvi !== null && data.ndvi !== undefined) {
      const ndvi = data.ndvi;
      const pct = Math.min(Math.max(ndvi * 100, 0), 100);
      let color = "var(--accent-dark)";
      let healthClass = "health-good";
      let healthText = "Healthy canopy";

      if (ndvi < 0.2) {
        color = "var(--red)";
        healthClass = "health-poor";
        healthText = "Low vegetation signal";
      } else if (ndvi < 0.4) {
        color = "var(--gold)";
        healthClass = "health-moderate";
        healthText = "Moderate crop vigor";
      }

      container.innerHTML += '<article class="result-card"><div class="result-kicker">Vegetation Health</div><div class="ndvi-row"><div class="ndvi-value" style="color: ' + color + ';">' + ndvi.toFixed(4) + '</div><div class="health-pill ' + healthClass + '">' + healthText + '</div></div><div class="track"><div class="fill" id="ndvi-fill" style="background: ' + color + ';"></div></div></article>';

      setTimeout(function () {
        const fill = document.getElementById("ndvi-fill");
        if (fill) fill.style.width = pct + "%";
      }, 80);
    } else {
      container.innerHTML += '<article class="result-card"><div class="result-kicker">Vegetation Health</div><p style="color: var(--text-soft); font-size: 0.92rem; line-height: 1.6;">NDVI was not available for this run, so the prediction used fallback seasonal behavior.</p></article>';
    }

    if (data.weather) {
      const weather = data.weather;
      const seasonRange = data.season_window ? data.season_window.start + " to " + data.season_window.end : "Season window unavailable";

      container.innerHTML += '<article class="result-card wide"><div class="result-kicker">Season Weather Snapshot</div><div class="metric-grid"><div class="metric"><span>Average temperature</span><strong>' + weather.temp + ' C</strong></div><div class="metric"><span>Rainfall</span><strong>' + weather.rainfall + ' mm</strong></div><div class="metric"><span>Humidity</span><strong>' + weather.humidity + ' %</strong></div><div class="metric"><span>Root soil moisture</span><strong>' + weather.soil + ' %</strong></div></div><div class="season-row"><div>' + seasonRange + '</div><div>' + weather.days + ' days sampled</div></div><div class="track" style="margin-top: 12px;"><div class="fill" id="season-fill" style="background: linear-gradient(90deg, #79c996, #1f9d55);"></div></div></article>';

      const maxDays = data.season === "Whole Year" ? 365 : 180;
      setTimeout(function () {
        const fill = document.getElementById("season-fill");
        if (fill) fill.style.width = Math.min((weather.days / maxDays) * 100, 100) + "%";
      }, 100);
    }
  }

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
