window.PLANE_RADAR_DEFAULTS = JSON.parse(document.getElementById("plane-radar-defaults").textContent);
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
    satellite: "Satélite", imageryCredit: "Imagery © Esri",
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
    satellite: "Satellite", imageryCredit: "Imagery © Esri",
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
const blipPlanes = new Map();
let radarAircraft = [];
let flightsRenderPending = false;
const SILHOUETTE_BASE_URL = "/api/silhouette/";
const GENERIC_SILHOUETTE_URL = "/static/paperplane.svg";
const unavailableSilhouettes = new Set();

const $ = (selector) => document.querySelector(selector);
const t = (key) => TRANSLATIONS[locale][key] || TRANSLATIONS["pt-BR"][key] || key;
function escapeHtml(value) {
  if (value == null) return "";
  return String(value).replace(/[&<>"']/g, (char) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"})[char]);
}
function safeImageUrl(url) {
  return /^(\/(?!\/)|https?:\/\/)/.test(String(url || "")) ? url : "";
}
function renderActiveUsers(count = 0) {
  const element = $("#active-users-label");
  const value = Number.parseInt(count, 10);
  if (element) element.innerHTML = t("activeUsers").replace("{count}", formatNumber(Number.isFinite(value) ? value : 0));
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
    renderActiveUsers(data.active_users);
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

function flightSilhouette(aircraft) {
  const typeCode = String(aircraft.t || "").trim().toUpperCase();
  if (!/^[A-Z0-9]{1,10}$/.test(typeCode)) return "";
  const source = unavailableSilhouettes.has(typeCode)
    ? GENERIC_SILHOUETTE_URL
    : `${SILHOUETTE_BASE_URL}${encodeURIComponent(typeCode)}`;
  const safeSource = safeImageUrl(source);
  if (!safeSource) return "";
  return `<span class="flight-silhouette-wrap"><img class="flight-silhouette" src="${escapeHtml(safeSource)}" data-type-code="${escapeHtml(typeCode)}" alt="" loading="lazy"></span>`;
}

function markSilhouetteUnavailable(typeCode, image) {
  unavailableSilhouettes.add(typeCode);
  delete image.dataset.typeCode;
  image.src = GENERIC_SILHOUETTE_URL;
}

document.addEventListener("error", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLImageElement) || !target.matches("img.flight-silhouette")) return;
  if (!target.dataset.typeCode || target.getAttribute("src") === GENERIC_SILHOUETTE_URL) return;
  markSilhouetteUnavailable(target.dataset.typeCode, target);
}, true);

function flightIata(aircraft) {
  const info = flightInfoByCallsign.get(String(aircraft.flight || "").trim());
  return String(info?.callsign_iata || "").trim();
}

function isMilitary(aircraft) {
  return aircraft.dbFlags === 1;
}

function aircraftName(aircraft) {
  const name = aircraft.t || t("unknown");
  return isMilitary(aircraft)
    ? `${escapeHtml(name)} <span class="military-badge" title="${t("militaryAircraft")}">=✪=</span>`
    : escapeHtml(name);
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
  return [code, name, municipality, country].filter(Boolean).map(escapeHtml).join(" · ");
}

function airlineDetails(info) {
  const airline = info?.airline;
  if (!airline) return t("unavailable");
  const country = airline.country || airline.country_iso || "";
  return `${escapeHtml(airline.name) || t("unavailable")}${country ? ` · ${escapeHtml(country)}` : ""}`;
}

function scheduleFlightsRender() {
  if (flightsRenderPending) return;
  flightsRenderPending = true;
  requestAnimationFrame(() => {
    flightsRenderPending = false;
    renderFlights(lastAircraft);
  });
}

function requestFlightInfo(callsign) {
  if (flightInfoByCallsign.has(callsign)) return Promise.resolve(flightInfoByCallsign.get(callsign));
  if (flightInfoRequests.has(callsign)) return flightInfoRequests.get(callsign);
  const request = fetch(`/api/flight-info?callsign=${encodeURIComponent(callsign)}`)
    .then((response) => response.ok ? response.json() : null)
    .catch(() => null)
    .then((info) => {
      if (info) flightInfoByCallsign.set(callsign, info);
      flightInfoRequests.delete(callsign);
      return info;
    });
  flightInfoRequests.set(callsign, request);
  return request;
}

async function loadTableFlightInfo(aircraft) {
  const callsigns = [...new Set(
    aircraft.map((plane) => String(plane.flight || "").trim()).filter(Boolean),
  )];
  await Promise.all(callsigns.map(async (callsign) => {
    if (flightInfoByCallsign.has(callsign)) return;
    await requestFlightInfo(callsign);
    scheduleFlightsRender();
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
  const data = await requestFlightInfo(callsign);
  if (!data) return;
  if (trackedAircraft && aircraftId(trackedAircraft) === trackedId) {
    flightInfo = data;
    renderFlightInfo();
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

$("#radar-blips").addEventListener("click", (event) => {
  const blip = event.target.closest(".blip");
  if (!blip) return;
  const plane = blipPlanes.get(blip.dataset.id);
  if (!plane) return;
  selectedAircraftId = aircraftId(plane);
  setTrackedAircraft(plane);
  renderRadar(radarAircraft);
});

function renderRadar(aircraft) {
  const layer = $("#radar-blips");
  layer.replaceChildren();
  radarAircraft = aircraft;
  blipPlanes.clear();
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
    blip.dataset.id = aircraftId(plane);
    if (aircraftId(plane) === selectedAircraftId) blip.classList.add("selected");
    blip.style.left = `${x}%`;
    blip.style.top = `${y}%`;
    blip.dataset.flight = formatFlight(plane);
    blip.title = `${formatFlight(plane)} · ${formatNumber(distance, 2)} NM`;
    blipPlanes.set(blip.dataset.id, plane);
    layer.appendChild(blip);
  });
  syncTrackedBlip();
}

function syncTrackedBlip() {
  if (!trackedAircraft || !trackedPosition) return;
  const id = aircraftId(trackedAircraft);
  if (!id) return;
  const blip = [...$("#radar-blips").children].find((element) => element.dataset.id === id);
  if (!blip) return;
  blip.style.left = `${trackedPosition.x}%`;
  blip.style.top = `${trackedPosition.y}%`;
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
  const silhouette = $("#tracked-silhouette");
  const silhouetteImage = $("#tracked-silhouette-image");
  if (!trackedAircraft || !trackedPosition) {
    marker.hidden = true;
    if (callsign) callsign.textContent = "—";
    if (trackedCaption) trackedCaption.textContent = "—";
    if (speedCaption) speedCaption.textContent = "—";
    if (silhouette) silhouette.hidden = true;
    if (silhouetteImage) silhouetteImage.style.transform = "";
    return;
  }
  marker.hidden = false;
  marker.style.left = `${trackedPosition.x}%`;
  marker.style.top = `${trackedPosition.y}%`;
  syncTrackedBlip();
  if (callsign) callsign.textContent = formatFlight(trackedAircraft);
  if (trackedCaption) trackedCaption.textContent = formatFlight(trackedAircraft);
  if (speedCaption) speedCaption.textContent = formatNumber(trackedAircraft.gs, 1);
  if (silhouette && silhouetteImage) {
    const typeCode = String(trackedAircraft.t || "").trim().toUpperCase();
    const silhouetteHeading = Number(trackedAircraft.track ?? trackedAircraft.dir);
    silhouette.hidden = !typeCode;
    silhouetteImage.hidden = !typeCode;
    silhouetteImage.alt = typeCode ? `Silhouette ${typeCode}` : "";
    silhouetteImage.style.transform = Number.isFinite(silhouetteHeading)
      ? `rotate(${silhouetteHeading}deg)`
      : "";
    silhouetteImage.onerror = () => {
      unavailableSilhouettes.add(typeCode);
      silhouetteImage.onerror = null;
      silhouetteImage.dataset.source = GENERIC_SILHOUETTE_URL;
      silhouetteImage.src = GENERIC_SILHOUETTE_URL;
    };
    if (typeCode) {
      const source = unavailableSilhouettes.has(typeCode)
        ? GENERIC_SILHOUETTE_URL
        : `${SILHOUETTE_BASE_URL}${encodeURIComponent(typeCode)}`;
      if (silhouetteImage.dataset.source !== source) {
        silhouetteImage.dataset.source = source;
        silhouetteImage.src = source;
      }
    }
  }
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
        <td data-label="${t("flight")}"><div class="flight-cell"><span class="flight-silhouette-container">${flightSilhouette(plane)}</span><span><span class="flight-code">${escapeHtml(formatFlight(plane))}</span>${flightIata(plane) ? `<span class="flight-iata">${escapeHtml(flightIata(plane))}</span>` : ""}<span class="subtext">${escapeHtml(plane.hex) || "—"} · ${escapeHtml(plane.r) || `${t("unavailable")}`}</span></span></div></td>
        <td data-label="${t("airline")}">${airlineDetails(flightInfoByCallsign.get(String(plane.flight || "").trim()))}</td>
        <td data-label="${t("route")}"><span class="subtext">${locationDetails(flightInfoByCallsign.get(String(plane.flight || "").trim())?.origin, "originUnknown")}</span><span class="subtext">${locationDetails(flightInfoByCallsign.get(String(plane.flight || "").trim())?.destination, "destinationUnknown")}</span></td>
        <td data-label="${t("aircraft")}">${aircraftName(plane)}<span class="subtext">${escapeHtml(plane.desc) || `${t("unknown")} ${t("aircraft").toLowerCase()}`}</span></td>
        <td data-label="${t("altitude")}">${formatAltitude(plane)}</td>
        <td data-label="${t("speed")}">${plane.gs == null ? "—" : `${formatNumber(plane.gs, 1)} kt`}</td>
        <td data-label="${t("heading")}">${plane.track == null ? "—" : `${formatNumber(plane.track, 0)}°`}</td>
        <td data-label="${t("distance")}">${plane.dst == null ? "—" : `${formatNumber(plane.dst, 2)} NM`}</td>
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
  updateSatelliteView();
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

/* Satellite background for the radar.
 * The radar circle spans 2 * 0.44 * width px for dist NM radius (positionOnRadar uses 44%).
 * We pick the smallest integer Web Mercator zoom whose ground resolution is finer than the
 * radar needs, then scale the whole tile grid by a fractional CSS scale so it matches exactly. */
const SATELLITE_STORAGE_KEY = "plane-radar-satellite";
const SATELLITE_MAX_ZOOM = 18;
const SATELLITE_RADIUS_RATIO = 0.44;
const METERS_PER_NM = 1852;
const EARTH_METERS_PER_PX_ZOOM0 = 156543.03392;
const TILE_SIZE = 256;
const satellite = {
  enabled: readSatellitePreference(),
  tiles: new Map(),
};

function readSatellitePreference() {
  try {
    return localStorage.getItem(SATELLITE_STORAGE_KEY) === "1";
  } catch (error) {
    return false;
  }
}

function saveSatellitePreference(enabled) {
  try {
    localStorage.setItem(SATELLITE_STORAGE_KEY, enabled ? "1" : "0");
  } catch (error) {
    console.warn("Unable to save satellite preference:", error);
  }
}

function computeSatelliteView() {
  const radar = $("#radar");
  const width = radar.clientWidth;
  const dist = Number(settings.dist);
  const lat = Number(settings.lat);
  const lon = Number(settings.lon);
  if (!width || !(dist > 0) || !Number.isFinite(lat) || !Number.isFinite(lon)) return null;

  // Ground metres that one screen pixel must cover at this radar scale.
  const metersPerScreenPx = (dist * METERS_PER_NM / SATELLITE_RADIUS_RATIO) / width;
  // Web Mercator is only defined up to ~85.05 degrees.
  const clampedLat = Math.max(-85.0511, Math.min(85.0511, lat));
  const phi = (clampedLat * Math.PI) / 180;
  const groundMetersPerPxZ0 = EARTH_METERS_PER_PX_ZOOM0 * Math.cos(phi);
  const zoom = Math.max(0, Math.min(SATELLITE_MAX_ZOOM,
    Math.ceil(Math.log2(groundMetersPerPxZ0 / metersPerScreenPx))));
  const tileMeters = groundMetersPerPxZ0 / 2 ** zoom;
  // Each tile pixel is drawn at this many screen pixels (<= 1 by construction).
  const scale = tileMeters / metersPerScreenPx;

  const worldSize = TILE_SIZE * 2 ** zoom;
  const normalizedLon = ((((lon + 180) % 360) + 360) % 360);
  const centerX = (normalizedLon / 360) * worldSize;
  const centerY = ((1 - Math.log(Math.tan(phi) + 1 / Math.cos(phi)) / Math.PI) / 2) * worldSize;

  // Visible half-extent in tile pixels, plus one tile of margin on every side.
  const halfExtent = width / 2 / scale;
  return {
    zoom,
    scale,
    centerX,
    centerY,
    tileCount: 2 ** zoom,
    minTx: Math.floor((centerX - halfExtent) / TILE_SIZE) - 1,
    maxTx: Math.floor((centerX + halfExtent) / TILE_SIZE) + 1,
    minTy: Math.floor((centerY - halfExtent) / TILE_SIZE) - 1,
    maxTy: Math.floor((centerY + halfExtent) / TILE_SIZE) + 1,
  };
}

function createSatelliteTile(key, zoom, x, y) {
  const img = document.createElement("img");
  img.className = "satellite-tile";
  img.alt = "";
  img.decoding = "async";
  img.draggable = false;
  img.addEventListener("load", () => img.classList.add("is-loaded"), {once: true});
  img.addEventListener("error", () => {
    img.remove();
    if (satellite.tiles.get(key) === img) satellite.tiles.delete(key);
  }, {once: true});
  img.src = `/api/satellite-tile/${zoom}/${x}/${y}`;
  return img;
}

function clearSatelliteTiles() {
  satellite.tiles.forEach((img) => img.remove());
  satellite.tiles.clear();
}

function updateSatelliteView() {
  const layer = $("#satellite-layer");
  const map = $("#satellite-map");
  const credit = $("#satellite-credit");
  if (!layer || !map) return;
  layer.hidden = !satellite.enabled;
  if (credit) credit.hidden = !satellite.enabled;
  if (!satellite.enabled) {
    clearSatelliteTiles();
    return;
  }
  const view = computeSatelliteView();
  if (!view) return;

  // Container sits at the radar centre; tiles are offset from that centre in tile pixels
  // and the whole container is scaled, so the radar centre always matches centerX/centerY.
  map.style.transform = `scale(${view.scale})`;

  const needed = new Set();
  for (let ty = Math.max(0, view.minTy); ty <= Math.min(view.tileCount - 1, view.maxTy); ty++) {
    for (let tx = view.minTx; tx <= view.maxTx; tx++) {
      const key = `${view.zoom}:${tx}:${ty}`;
      needed.add(key);
      let img = satellite.tiles.get(key);
      if (!img) {
        const wrappedX = ((tx % view.tileCount) + view.tileCount) % view.tileCount;
        img = createSatelliteTile(key, view.zoom, wrappedX, ty);
        satellite.tiles.set(key, img);
        map.appendChild(img);
      }
      img.style.left = `${tx * TILE_SIZE - view.centerX}px`;
      img.style.top = `${ty * TILE_SIZE - view.centerY}px`;
    }
  }
  satellite.tiles.forEach((img, key) => {
    if (needed.has(key)) return;
    img.remove();
    satellite.tiles.delete(key);
  });
}

function setSatelliteEnabled(enabled) {
  satellite.enabled = enabled;
  saveSatellitePreference(enabled);
  $("#satellite-toggle").setAttribute("aria-pressed", String(enabled));
  updateSatelliteView();
}

$("#satellite-toggle").addEventListener("click", () => setSatelliteEnabled(!satellite.enabled));
if ("ResizeObserver" in window) {
  new ResizeObserver(() => updateSatelliteView()).observe($("#radar"));
}
$("#satellite-toggle").setAttribute("aria-pressed", String(satellite.enabled));

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
