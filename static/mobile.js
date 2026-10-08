const MOBILE_POLL_INTERVAL = Number(window.PLANE_RADAR_DEFAULTS.polling) || 5;
const MOBILE_TRANSLATIONS = {
  "pt-BR": {brandTitle:"Lá<span> em Cima</span>!",language:"Idioma",live:"Ao vivo",offline:"Offline",radarVersion:"Versão radar",liveTraffic:"TRÁFEGO AO VIVO",detectedFlights:"Voos detectados",latitude:"Latitude",longitude:"Longitude",radius:"Raio",updateArea:"Atualizar área",aircraftDetected:"aeronaves detectadas",flight:"Voo",airline:"Companhia aérea",route:"Rota",aircraft:"Aeronave",altitude:"Altitude",speed:"Velocidade",heading:"Proa",distance:"Distância",militaryAircraft:"Aeronave militar",searchingAirspace:"Pesquisando o espaço aéreo…",noAircraft:"Nenhuma aeronave detectada nesta área.",unknown:"Desconhecido",unavailable:"indisponível",onGround:"No solo",originUnknown:"Origem desconhecida",destinationUnknown:"Destino desconhecido",updated:"Atualizado",now:"agora"},
  "en-US": {brandTitle:"Up<span>There</span>!",language:"Language",live:"Live",offline:"Offline",radarVersion:"Radar version",liveTraffic:"LIVE TRAFFIC",detectedFlights:"Detected flights",latitude:"Latitude",longitude:"Longitude",radius:"Radius",updateArea:"Update area",aircraftDetected:"aircraft detected",flight:"Flight",airline:"Airline",route:"Route",aircraft:"Aircraft",altitude:"Altitude",speed:"Speed",heading:"Heading",distance:"Distance",militaryAircraft:"Military aircraft",searchingAirspace:"Searching the airspace…",noAircraft:"No aircraft detected in this area.",unknown:"Unknown",unavailable:"unavailable",onGround:"On ground",originUnknown:"Unknown origin",destinationUnknown:"Unknown destination",updated:"Updated",now:"now"}
};
let mobileLocale = localStorage.getItem("plane-radar-locale") || "pt-BR";
let mobileSettings = {...window.PLANE_RADAR_DEFAULTS};
let mobileAircraft = [];
const mobileInfo = new Map();
let mobileLocationInfo = null;
let mobileLocationRequestKey = null;
const $m = (selector) => document.querySelector(selector);
const tm = (key) => MOBILE_TRANSLATIONS[mobileLocale][key] || key;
const number = (value, digits = 0) => Number.isFinite(Number(value)) ? Number(value).toLocaleString(mobileLocale, {maximumFractionDigits: digits}) : "—";

function renderMobileLocation() {
  const label = $m("#mobile-location-label");
  if (!label) return;
  label.querySelector(".location-city").textContent = mobileLocationInfo?.city || "";
  label.querySelector(".location-region").textContent = mobileLocationInfo?.principalsubdivision || "";
  label.querySelector(".location-country").textContent = mobileLocationInfo?.countryname || "";
  label.hidden = !mobileLocationInfo;
}
async function loadMobileLocation() {
  const localityLanguage = mobileLocale === "pt-BR" ? "pt" : "en";
  const key = `${mobileSettings.lat},${mobileSettings.lon},${localityLanguage}`;
  if (key === mobileLocationRequestKey) return;
  mobileLocationRequestKey = key;
  mobileLocationInfo = null;
  renderMobileLocation();
  try {
    const response = await fetch(`/api/location?lat=${encodeURIComponent(mobileSettings.lat)}&lon=${encodeURIComponent(mobileSettings.lon)}&localityLanguage=${localityLanguage}`);
    if (!response.ok) throw new Error("Location lookup failed");
    mobileLocationInfo = await response.json();
    renderMobileLocation();
  } catch (error) { console.warn("Unable to load location:", error); }
}

function airport(airportData, fallback) {
  if (!airportData) return tm(fallback);
  return [airportData.iata_code || airportData.icao_code, airportData.name, airportData.municipality, airportData.country_name || airportData.country_iso_name].filter(Boolean).join(" · ");
}
function flightInfo(plane) { return mobileInfo.get(String(plane.flight || "").trim()); }
function aircraftName(plane) {
  const name = plane.t || tm("unknown");
  return plane.dbFlags === 1
    ? `${name} <span class="military-badge" title="${tm("militaryAircraft")}">=✪=</span>`
    : name;
}
function renderMobileTable() {
  const list = $m("#mobile-flight-list");
  if (!mobileAircraft.length) { list.innerHTML = `<tr><td colspan="8" class="empty-state">${tm("noAircraft")}</td></tr>`; return; }
  list.innerHTML = mobileAircraft.map((plane) => {
    const info = flightInfo(plane); const airline = info?.airline;
    return `<tr><td><span class="flight-code">${(plane.flight || plane.hex || tm("unknown")).trim()}</span><span class="subtext">${plane.hex || "—"} · ${plane.r || tm("unavailable")}</span></td>
      <td>${airline ? `${airline.name || tm("unavailable")}${airline.country ? ` · ${airline.country}` : ""}` : tm("unavailable")}</td>
      <td><span class="subtext">${airport(info?.origin, "originUnknown")}</span><span class="subtext">${airport(info?.destination, "destinationUnknown")}</span></td>
      <td>${aircraftName(plane)}<span class="subtext">${plane.desc || tm("unavailable")}</span></td>
      <td>${plane.alt_baro === "ground" ? tm("onGround") : plane.alt_baro == null ? "—" : `${number(plane.alt_baro)} ft`}</td>
      <td>${plane.gs == null ? "—" : `${number(plane.gs, 1)} kt`}</td><td>${plane.track == null ? "—" : `${number(plane.track)}°`}</td><td>${plane.dst == null ? "—" : `${number(plane.dst, 2)} NM`}</td></tr>`;
  }).join("");
}
function applyMobileLocale() {
  document.documentElement.lang = mobileLocale;
  document.querySelectorAll("[data-i18n]").forEach((element) => { element.textContent = tm(element.dataset.i18n); });
  document.querySelectorAll("[data-i18n-html]").forEach((element) => { element.innerHTML = tm(element.dataset.i18nHtml); });
  $m("#mobile-language-select").value = mobileLocale; renderMobileTable();
}
async function enrichMobileFlights(aircraft) {
  await Promise.all([...new Set(aircraft.map((p) => String(p.flight || "").trim()).filter(Boolean))].map(async (callsign) => {
    if (mobileInfo.has(callsign)) return;
    try { const response = await fetch(`/api/flight-info?callsign=${encodeURIComponent(callsign)}`); if (response.ok) mobileInfo.set(callsign, await response.json()); } catch (error) { console.warn("Flight info unavailable", error); }
  }));
  renderMobileTable();
}
async function loadMobileAircraft() {
  try {
    const query = new URLSearchParams(mobileSettings); const response = await fetch(`/api/aircraft?${query}`); const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Unable to load aircraft.");
    mobileAircraft = data.aircraft || []; $m("#mobile-count").textContent = number(mobileAircraft.length); renderMobileTable(); enrichMobileFlights(mobileAircraft);
    $m("#mobile-status").textContent = tm("live"); $m("#mobile-connection").classList.remove("status-error"); $m("#mobile-refresh").textContent = `${tm("updated")} ${new Date().toLocaleTimeString(mobileLocale, {hour:"2-digit", minute:"2-digit"})}`;
  } catch (error) { $m("#mobile-status").textContent = tm("offline"); $m("#mobile-connection").classList.add("status-error"); $m("#mobile-message").textContent = error.message; $m("#mobile-message").hidden = false; }
  setTimeout(loadMobileAircraft, MOBILE_POLL_INTERVAL * 1000);
}
document.querySelectorAll("[data-i18n]");
$m("#mobile-language-select").addEventListener("change", (event) => { mobileLocale = event.target.value; localStorage.setItem("plane-radar-locale", mobileLocale); applyMobileLocale(); loadMobileLocation(); });
$m("#mobile-settings-form").addEventListener("submit", (event) => { event.preventDefault(); mobileSettings = Object.fromEntries(new FormData(event.currentTarget)); loadMobileLocation(); loadMobileAircraft(); });
applyMobileLocale(); $m("#mobile-settings-form button[type='submit']").click();
