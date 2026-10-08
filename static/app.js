const POLL_INTERVAL = Number(window.PLANE_RADAR_DEFAULTS.polling) || 10;
const TRANSLATIONS = {
  "pt-BR": {
    brandTitle: "Lá<span> em Cima</span>!", language: "Idioma", connecting: "Conectando", live: "Ao vivo", offline: "Offline", mobileVersion: "Versão mobile", mobileSuggestion: "Você está em um dispositivo móvel. Quer usar a versão otimizada?", openMobile: "Abrir versão mobile",
    trackingArea: "ÁREA DE RASTREAMENTO", whatIsOverhead: "O que está sobrevoando?",
    latitude: "Latitude", longitude: "Longitude", radius: "Raio", updateArea: "Atualizar área",
    airspaceRadar: "RADAR DO ESPAÇO AÉREO", aircraftNearby: "Aeronaves próximas",
    tracking: "Rastreando", groundspeed: "velocidade no solo", inAirspace: "NO ESPAÇO AÉREO",
    aircraftDetected: "aeronaves detectadas", closestAircraft: "AERONAVE MAIS PRÓXIMA",
    nauticalMilesAway: "milhas náuticas de distância", nextRefresh: "PRÓXIMA ATUALIZAÇÃO",
    automaticPolling: "consulta automática", liveTraffic: "TRÁFEGO AO VIVO",
    detectedFlights: "Voos detectados", flight: "Voo", aircraft: "Aeronave",
    airline: "Companhia aérea", route: "Rota",
    altitude: "Altitude", speed: "Velocidade", heading: "Proa", distance: "Distância",
    source: "Fonte",
    searchingAirspace: "Pesquisando o espaço aéreo…", noAircraft: "Nenhuma aeronave detectada nesta área.",
    unknown: "Desconhecido", onGround: "No solo", unavailable: "indisponível",
    routeUnavailable: "Rota não disponível", originUnknown: "Origem desconhecida", destinationUnknown: "Destino desconhecido", militaryAircraft: "Aeronave militar",
    updated: "Atualizado", now: "agora", footer: "Dados fornecidos por transponders de aeronaves ADS-B. Altitudes em pés e velocidades em nós.",
    radarAriaLabel: "Radar de aeronaves próximas", activeUsers: "<strong>{count}</strong> sessões olhando lá <span>pra cima</span>!",
  },
  "en-US": {
    brandTitle: "Up<span>There</span>!", language: "Language", connecting: "Connecting", live: "Live", offline: "Offline", mobileVersion: "Mobile version", mobileSuggestion: "You are on a mobile device. Would you like to use the optimized version?", openMobile: "Open mobile version",
    trackingArea: "TRACKING AREA", whatIsOverhead: "What is overhead?",
    latitude: "Latitude", longitude: "Longitude", radius: "Radius", updateArea: "Update area",
    airspaceRadar: "AIRSPACE RADAR", aircraftNearby: "Aircraft nearby",
    tracking: "Tracking", groundspeed: "groundspeed", inAirspace: "IN AIRSPACE",
    aircraftDetected: "aircraft detected", closestAircraft: "CLOSEST AIRCRAFT",
    nauticalMilesAway: "nautical miles away", nextRefresh: "NEXT REFRESH",
    automaticPolling: "automatic polling", liveTraffic: "LIVE TRAFFIC",
    detectedFlights: "Detected flights", flight: "Flight", aircraft: "Aircraft",
    airline: "Airline", route: "Route",
    altitude: "Altitude", speed: "Speed", heading: "Heading", distance: "Distance",
    source: "Source",
    searchingAirspace: "Searching the airspace…", noAircraft: "No aircraft detected in this area.",
    unknown: "Unknown", onGround: "On ground", unavailable: "unavailable",
    routeUnavailable: "Route unavailable", originUnknown: "Unknown origin", destinationUnknown: "Unknown destination", militaryAircraft: "Military aircraft",
    updated: "Updated", now: "now", footer: "Data provided by ADS-B aircraft transponders. Altitudes are in feet, speeds are in knots.",
    radarAriaLabel: "Radar view of nearby aircraft", activeUsers: "<strong>{count}</strong> sessions looking up <span>there</span>!",
  },
};
let locale = localStorage.getItem("plane-radar-locale") || "pt-BR";
const SETTINGS_STORAGE_KEY = "plane-radar-settings";
const DEFAULT_SETTINGS = {
  lat: window.PLANE_RADAR_DEFAULTS.latitude,
  lon: window.PLANE_RADAR_DEFAULTS.longitude,
  dist: window.PLANE_RADAR_DEFAULTS.distance,
  polling: window.PLANE_RADAR_DEFAULTS.polling,
};
function readSessionSettings() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(SETTINGS_STORAGE_KEY) || "null");
    if (!saved || !Number.isFinite(Number(saved.lat)) || !Number.isFinite(Number(saved.lon)) || !Number.isFinite(Number(saved.dist))) {
      return {...DEFAULT_SETTINGS};
    }
    return {...DEFAULT_SETTINGS, lat: saved.lat, lon: saved.lon, dist: saved.dist};
  } catch (error) {
    return {...DEFAULT_SETTINGS};
  }
}
function saveSessionSettings(settingsToSave) {
  try {
    sessionStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify({
      lat: settingsToSave.lat, lon: settingsToSave.lon, dist: settingsToSave.dist,
    }));
  } catch (error) {
    console.warn("Unable to save tracking settings:", error);
  }
}
let settings = readSessionSettings();
let secondsUntilRefresh = 0;
let countdownTimer;
let trackedAircraft = null;
let trackedPosition = null;
let trackedUpdatedAt = 0;
let selectedAircraftId = null;
let lastAircraft = [];
let lastUpdateAt = null;
let flightInfo = null;
let locationInfo = null;
let locationRequestKey = null;
const flightInfoByCallsign = new Map();
const flightInfoRequests = new Map();

const $ = (selector) => document.querySelector(selector);
const t = (key) => TRANSLATIONS[locale][key] || TRANSLATIONS["pt-BR"][key] || key;
function renderActiveUsers(count = "—") {
  const element = $("#active-users-label");
  if (element) element.innerHTML = t("activeUsers").replace("{count}", count);
}

function getPresenceClientId() {
  const key = "plane-radar-presence-id";
  let clientId = localStorage.getItem(key);
  if (!clientId) {
    clientId = window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
    localStorage.setItem(key, clientId);
  }
  return clientId;
}

async function updatePresence() {
  try {
    const response = await fetch("/api/presence", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({client_id: getPresenceClientId()}),
    });
    if (!response.ok) return;
    const data = await response.json();
    renderActiveUsers(formatNumber(data.active_users));
  } catch (error) {
    console.warn("Unable to update active user count:", error);
  }
}

function applyLocale() {
  document.documentElement.lang = locale;
  document.querySelectorAll("[data-i18n]").forEach((element) => {
    element.textContent = t(element.dataset.i18n);
  });
  document.querySelectorAll("[data-i18n-html]").forEach((element) => {
    element.innerHTML = t(element.dataset.i18nHtml);
  });
  document.querySelectorAll("[data-i18n-attr]").forEach((element) => {
    element.dataset.i18nAttr.split(",").forEach((attribute) => {
      const [name, key] = attribute.split(":");
      element.setAttribute(name, t(key));
    });
  });
  $("#language-select").value = locale;
  renderFlights(lastAircraft);
  renderFlightInfo();
  if (lastUpdateAt) updateLastUpdate();
}

function formatNumber(value, digits = 0) {
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString(locale, {maximumFractionDigits: digits}) : "—";
}

function renderLocation() {
  const label = $("#location-label");
  if (!label) return;
  const city = label.querySelector(".location-city");
  const region = label.querySelector(".location-region");
  const country = label.querySelector(".location-country");
  city.textContent = locationInfo?.city || "";
  region.textContent = locationInfo?.principalsubdivision || "";
  country.textContent = locationInfo?.countryname || "";
  label.hidden = !locationInfo;
}

async function loadLocation(force = false) {
  const localityLanguage = locale === "pt-BR" ? "pt" : "en";
  const key = `${settings.lat},${settings.lon},${localityLanguage}`;
  if (!force && key === locationRequestKey && locationInfo) return;
  locationRequestKey = key;
  locationInfo = null;
  renderLocation();
  try {
    const response = await fetch(`/api/location?lat=${encodeURIComponent(settings.lat)}&lon=${encodeURIComponent(settings.lon)}&localityLanguage=${localityLanguage}`);
    if (!response.ok) throw new Error("Location lookup failed");
    locationInfo = await response.json();
    renderLocation();
  } catch (error) {
    locationRequestKey = null;
    console.warn("Unable to load location:", error);
  }
}

function numeric(value) {
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function relativePosition(plane) {
  const planeLat = numeric(plane.lat);
  const planeLon = numeric(plane.lon);
  const centerLat = numeric(settings.lat);
  const centerLon = numeric(settings.lon);
  if (planeLat === null || planeLon === null || centerLat === null || centerLon === null) {
    const distance = numeric(plane.dst);
    const bearing = numeric(plane.dir);
    return distance !== null && bearing !== null ? {distance, bearing} : null;
  }

  const earthRadiusNm = 3440.065;
  const toRadians = (degrees) => (degrees * Math.PI) / 180;
  const latitude1 = toRadians(centerLat);
  const latitude2 = toRadians(planeLat);
  const deltaLatitude = toRadians(planeLat - centerLat);
  const deltaLongitude = toRadians(planeLon - centerLon);
  const haversine = Math.sin(deltaLatitude / 2) ** 2
    + Math.cos(latitude1) * Math.cos(latitude2) * Math.sin(deltaLongitude / 2) ** 2;
  const distance = 2 * earthRadiusNm * Math.asin(Math.sqrt(haversine));
  const bearing = (Math.atan2(
    Math.sin(deltaLongitude) * Math.cos(latitude2),
    Math.cos(latitude1) * Math.sin(latitude2)
      - Math.sin(latitude1) * Math.cos(latitude2) * Math.cos(deltaLongitude),
  ) * 180 / Math.PI + 360) % 360;
  return {distance, bearing};
}

function formatAltitude(aircraft) {
  const altitude = aircraft.alt_baro ?? aircraft.alt_geom;
  if (altitude === "ground") return t("onGround");
  return altitude == null ? "—" : `${formatNumber(altitude)} ft`;
}

function formatFlight(aircraft) {
  return (aircraft.flight || aircraft.hex || t("unknown")).trim() || aircraft.hex || t("unknown");
}

function isMilitary(aircraft) {
  return aircraft.dbFlags === 1;
}

function aircraftName(aircraft) {
  const name = aircraft.t || t("unknown");
  return isMilitary(aircraft)
    ? `${name} <span class="military-badge" title="${t("militaryAircraft")}">=✪=</span>`
    : name;
}

function aircraftId(aircraft) {
  return aircraft.hex || aircraft.icao || String(aircraft.flight || "").trim() || aircraft.r;
}

function airportLabel(airport, fallback) {
  if (!airport) return t(fallback);
  return airport.iata_code || airport.icao_code || airport.municipality || airport.name || t(fallback);
}

function locationDetails(airport, fallback) {
  if (!airport) return t(fallback);
  const code = airport.iata_code || airport.icao_code || "—";
  const name = airport.name || "";
  const municipality = airport.municipality || "";
  const country = airport.country_name || airport.country_iso_name || "";
  return [code, name, municipality, country].filter(Boolean).join(" · ");
}

function airlineDetails(info) {
  const airline = info?.airline;
  if (!airline) return t("unavailable");
  const country = airline.country || airline.country_iso || "";
  return `${airline.name || t("unavailable")}${country ? ` · ${country}` : ""}`;
}

async function loadTableFlightInfo(aircraft) {
  const callsigns = [...new Set(
    aircraft.map((plane) => String(plane.flight || "").trim()).filter(Boolean),
  )];
  await Promise.all(callsigns.map(async (callsign) => {
    if (flightInfoByCallsign.has(callsign) || flightInfoRequests.has(callsign)) return;
    const request = fetch(`/api/flight-info?callsign=${encodeURIComponent(callsign)}`)
      .then((response) => response.ok ? response.json() : null)
      .catch(() => null)
      .then((info) => {
        if (info) flightInfoByCallsign.set(callsign, info);
        flightInfoRequests.delete(callsign);
        renderFlights(lastAircraft);
      });
    flightInfoRequests.set(callsign, request);
    await request;
  }));
}

function renderFlightInfo() {
  const panel = $("#flight-info");
  if (!panel) return;
  if (!flightInfo) {
    panel.hidden = true;
    return;
  }
  panel.hidden = false;
  $("#flight-airline").textContent = flightInfo.airline?.name || t("routeUnavailable");
  $("#flight-origin").textContent = airportLabel(flightInfo.origin, "originUnknown");
  $("#flight-destination").textContent = airportLabel(flightInfo.destination, "destinationUnknown");
}

async function loadFlightInfo(aircraft) {
  const callsign = String(aircraft?.flight || "").trim();
  flightInfo = null;
  renderFlightInfo();
  if (!callsign) return;
  const trackedId = aircraftId(aircraft);
  try {
    const response = await fetch(`/api/flight-info?callsign=${encodeURIComponent(callsign)}`);
    if (!response.ok) return;
    const data = await response.json();
    if (trackedAircraft && aircraftId(trackedAircraft) === trackedId) {
      flightInfo = data;
      renderFlightInfo();
    }
  } catch (error) {
    console.warn("Unable to load flight route information:", error);
  }
}

function setTrackedAircraft(aircraft) {
  const previousId = trackedAircraft && aircraftId(trackedAircraft);
  trackedAircraft = aircraft || null;
  if (!trackedAircraft) {
    trackedPosition = null;
    flightInfo = null;
    renderTrackedAircraft();
    renderFlightInfo();
    return;
  }
  const position = relativePosition(trackedAircraft);
  if (!position) {
    trackedPosition = null;
    renderTrackedAircraft();
    return;
  }
  trackedPosition = positionOnRadar(position.distance, position.bearing);
  trackedUpdatedAt = performance.now();
  renderTrackedAircraft();
  if (aircraftId(trackedAircraft) !== previousId) loadFlightInfo(trackedAircraft);
}

function renderRadar(aircraft) {
  const layer = $("#radar-blips");
  layer.innerHTML = "";
  aircraft.forEach((plane) => {
    const position = relativePosition(plane);
    if (!position) return;
    const {distance, bearing} = position;
    const radius = Math.min(44, (distance / Number(settings.dist)) * 44);
    const radians = (bearing * Math.PI) / 180;
    const x = 50 + Math.sin(radians) * radius;
    const y = 50 - Math.cos(radians) * radius;
    const blip = document.createElement("span");
    blip.className = "blip";
    if (aircraftId(plane) === selectedAircraftId) blip.classList.add("selected");
    blip.style.left = `${x}%`;
    blip.style.top = `${y}%`;
    blip.dataset.flight = formatFlight(plane);
    blip.title = `${formatFlight(plane)} · ${formatNumber(distance, 2)} NM`;
    blip.addEventListener("click", () => {
      selectedAircraftId = aircraftId(plane);
      setTrackedAircraft(plane);
      renderRadar(aircraft);
    });
    layer.appendChild(blip);
  });
}

function positionOnRadar(distance, bearing) {
  const radius = Math.min(44, (distance / Number(settings.dist)) * 44);
  const radians = (bearing * Math.PI) / 180;
  return {
    x: 50 + Math.sin(radians) * radius,
    y: 50 - Math.cos(radians) * radius,
  };
}

function renderTrackedAircraft() {
  const marker = $("#tracked-aircraft");
  if (!marker) return;
  const callsign = $("#tracked-callsign");
  const trackedCaption = $("#tracked-caption");
  const speedCaption = $("#speed-caption");
  if (!trackedAircraft || !trackedPosition) {
    marker.hidden = true;
    if (callsign) callsign.textContent = "—";
    if (trackedCaption) trackedCaption.textContent = "—";
    if (speedCaption) speedCaption.textContent = "—";
    return;
  }
  marker.hidden = false;
  marker.style.left = `${trackedPosition.x}%`;
  marker.style.top = `${trackedPosition.y}%`;
  if (callsign) callsign.textContent = formatFlight(trackedAircraft);
  if (trackedCaption) trackedCaption.textContent = formatFlight(trackedAircraft);
  if (speedCaption) speedCaption.textContent = formatNumber(trackedAircraft.gs, 1);
  const heading = Number(trackedAircraft.track);
  const icon = $(".tracked-icon svg");
  if (icon && Number.isFinite(heading)) {
    icon.style.transform = `rotate(${heading}deg)`;
  }
}

function trackClosestAircraft(aircraft) {
  const candidates = aircraft
    .map((plane) => ({plane, position: relativePosition(plane)}))
    .filter((item) => item.position);
  const selected = selectedAircraftId
    ? candidates.find((item) => aircraftId(item.plane) === selectedAircraftId)
    : null;
  const closest = candidates.sort((a, b) => a.position.distance - b.position.distance)[0];
  setTrackedAircraft((selected || closest)?.plane);
}

function moveTrackedAircraft(timestamp) {
  if (trackedAircraft && trackedPosition) {
    const elapsedSeconds = (timestamp - trackedUpdatedAt) / 1000;
    const speed = numeric(trackedAircraft.gs);
    const heading = numeric(trackedAircraft.track) ?? numeric(trackedAircraft.dir);
    if (Number.isFinite(speed) && Number.isFinite(heading)) {
      const distance = (speed * elapsedSeconds) / 3600;
      const radians = (heading * Math.PI) / 180;
      const scale = 44 / Number(settings.dist);
      trackedPosition.x = 50 + (trackedPosition.x - 50) + Math.sin(radians) * distance * scale;
      trackedPosition.y = 50 + (trackedPosition.y - 50) - Math.cos(radians) * distance * scale;
      trackedPosition.x = Math.max(7, Math.min(93, trackedPosition.x));
      trackedPosition.y = Math.max(7, Math.min(93, trackedPosition.y));
      trackedUpdatedAt = timestamp;
      renderTrackedAircraft();
    }
  }
  requestAnimationFrame(moveTrackedAircraft);
}

function renderFlights(aircraft) {
  const list = $("#flight-list");
  if (!aircraft.length) {
    list.innerHTML = `<tr><td colspan="8" class="empty-state">${t("noAircraft")}</td></tr>`;
    return;
  }
  list.innerHTML = aircraft
    .sort((a, b) => (a.dst ?? Infinity) - (b.dst ?? Infinity))
    .map((plane) => `
      <tr>
        <td><span class="flight-code">${formatFlight(plane)}</span><span class="subtext">${plane.hex || "—"} · ${plane.r || `${t("unavailable")}`}</span></td>
        <td>${airlineDetails(flightInfoByCallsign.get(String(plane.flight || "").trim()))}</td>
        <td><span class="subtext">${locationDetails(flightInfoByCallsign.get(String(plane.flight || "").trim())?.origin, "originUnknown")}</span><span class="subtext">${locationDetails(flightInfoByCallsign.get(String(plane.flight || "").trim())?.destination, "destinationUnknown")}</span></td>
        <td>${aircraftName(plane)}<span class="subtext">${plane.desc || `${t("unknown")} ${t("aircraft").toLowerCase()}`}</span></td>
        <td>${formatAltitude(plane)}</td>
        <td>${plane.gs == null ? "—" : `${formatNumber(plane.gs, 1)} kt`}</td>
        <td>${plane.track == null ? "—" : `${formatNumber(plane.track, 0)}°`}</td>
        <td>${plane.dst == null ? "—" : `${formatNumber(plane.dst, 2)} NM`}</td>
      </tr>
    `).join("");
}

function updateLastUpdate() {
  if (lastUpdateAt) {
    $("#last-update").textContent = `${t("updated")} ${lastUpdateAt.toLocaleTimeString(locale, {hour: "2-digit", minute: "2-digit"})}`;
  }
}

function setStatus(connected, text) {
  $("#connection-status").classList.toggle("status-error", !connected);
  $("#status-text").textContent = text;
}

function showMessage(text) {
  const element = $("#message");
  element.textContent = text;
  element.hidden = !text;
}

async function loadAircraft() {
  const query = new URLSearchParams(settings);
  try {
    const response = await fetch(`/api/aircraft?${query}`);
    const data = await readJsonResponse(response);
    if (!response.ok) throw new Error(data.error || "Unable to load aircraft.");
    const aircraft = data.aircraft || [];
    lastAircraft = aircraft;
    renderFlights(aircraft);
    loadTableFlightInfo(aircraft);
    renderRadar(aircraft);
    trackClosestAircraft(aircraft);
    $("#aircraft-count").textContent = formatNumber(aircraft.length);
    const closest = aircraft.reduce((min, item) => Math.min(min, numeric(item.dst) ?? Infinity), Infinity);
    $("#closest-distance").textContent = Number.isFinite(closest) ? formatNumber(closest, 2) : "—";
    lastUpdateAt = new Date();
    updateLastUpdate();
    setStatus(true, t("live"));
    showMessage("");
  } catch (error) {
    setStatus(false, t("offline"));
    showMessage(error.message);
  } finally {
    secondsUntilRefresh = POLL_INTERVAL;
  }

  async function readJsonResponse(response) {
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
      throw new Error(`Server returned an unexpected response (${response.status}).`);
    }
    return response.json();
  }
}

function startCountdown() {
  clearInterval(countdownTimer);
  countdownTimer = setInterval(() => {
    secondsUntilRefresh -= 1;
    $("#countdown").textContent = secondsUntilRefresh > 0 ? `${secondsUntilRefresh}s` : t("now");
    if (secondsUntilRefresh <= 0) loadAircraft();
  }, 1000);
}

$("#settings-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const formData = new FormData(event.currentTarget);
  settings = Object.fromEntries(formData.entries());
  saveSessionSettings(settings);
  loadLocation();
  loadAircraft();
});

$("#language-select").addEventListener("change", (event) => {
  locale = event.target.value;
  localStorage.setItem("plane-radar-locale", locale);
  applyLocale();
  loadLocation(true);
  if (trackedAircraft) renderTrackedAircraft();
});

function isMobileDevice() {
  const mobileUserAgent = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
  const touchDevice = navigator.maxTouchPoints > 0 && window.matchMedia("(pointer: coarse)").matches;
  return mobileUserAgent || touchDevice;
}

const mobileSuggestion = $("#mobile-suggestion");
if (mobileSuggestion && isMobileDevice() && !localStorage.getItem("plane-radar-mobile-dismissed")) {
  mobileSuggestion.hidden = false;
  $("#dismiss-mobile").addEventListener("click", () => {
    mobileSuggestion.hidden = true;
    localStorage.setItem("plane-radar-mobile-dismissed", "1");
  });
}

applyLocale();
updatePresence();
setInterval(updatePresence, 15000);
Object.entries({lat: settings.lat, lon: settings.lon, dist: settings.dist}).forEach(([name, value]) => {
  $(`#settings-form [name="${name}"]`).value = value;
});
window.addEventListener("load", () => loadLocation(true), {once: true});
$("#settings-form button[type='submit']").click();
startCountdown();
requestAnimationFrame(moveTrackedAircraft);
