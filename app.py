import argparse
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
import threading
import time
from datetime import datetime, timezone

import requests
from PIL import Image
from resvg import render as render_svg
from resvg import usvg
from werkzeug.middleware.proxy_fix import ProxyFix
from flask import Flask, Response, jsonify, render_template, request, url_for

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

API_BASE_URL = "https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{distance}"
CALLSIGN_API_URL = "https://api.adsbdb.com/v0/callsign/{callsign}"
REVERSE_GEOCODE_API_URL = "https://api-bdc.io/data/reverse-geocode-client"
DEFAULT_LATITUDE = os.getenv("PLANE_RADAR_LAT", "-21.805684")
DEFAULT_LONGITUDE = os.getenv("PLANE_RADAR_LON", "-48.139653")
DEFAULT_DISTANCE = os.getenv("PLANE_RADAR_DISTANCE", "25")
DEFAULT_POLLING = int(os.getenv("PLANE_RADAR_POLLING", "10"))
AIRLINE_LOGO_API_KEY = os.getenv("PLANE_RADAR_AIRLINE_LOGO_API_KEY", "").strip()
CACHE_DB_PATH = os.getenv(
    "PLANE_RADAR_CACHE_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "planeradar-cache.sqlite3"),
)
REQUEST_TIMEOUT = 12
ADSB_MIN_REQUEST_INTERVAL = 2
PRESENCE_TIMEOUT = 45
FLIGHT_INFO_CACHE_TTL = 900
SILHOUETTE_CACHE_TTL = 259200
AIRLINE_LOGO_CACHE_TTL = 864000
AIRLINE_LOGO_CACHE_NAMESPACE = "airline_logo"
SILHOUETTE_PNG_CACHE_NAMESPACE = "silhouette_png_v2"
AIRLINE_LOGO_PNG_CACHE_NAMESPACE = "airline_logo_png"
PNG_CACHE_TTL = 31536000
MIN_IMAGE_SIZE = 16
MAX_IMAGE_SIZE = 256
MAX_DOWNLOAD_BYTES = 2 * 1024 * 1024
MAX_PRESENCE_IDS = 5000
CACHE_PURGE_INTERVAL = 600
ADSB_PAYLOAD_CACHE_TTL = 2
REVERSE_GEOCODE_CACHE_NAMESPACE = "reverse_geocode"
REVERSE_GEOCODE_CACHE_TTL = 86400
SVG_CONTENT_SECURITY_POLICY = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"
cache_lock = threading.Lock()
cache_db_local = threading.local()
adsb_request_lock = threading.Lock()
adsb_payload_cache_lock = threading.Lock()
presence_lock = threading.Lock()
active_presence = {}
adsb_payload_cache = {}
last_adsb_request_at = 0.0
last_cache_purge_at = float("-inf")


def open_cache_db():
    connection = getattr(cache_db_local, "connection", None)
    if connection is not None and cache_db_local.path == CACHE_DB_PATH:
        return connection
    if connection is not None:
        connection.close()
    cache_directory = os.path.dirname(CACHE_DB_PATH)
    if cache_directory:
        os.makedirs(cache_directory, exist_ok=True)
    connection = sqlite3.connect(CACHE_DB_PATH, timeout=30)
    connection.execute("PRAGMA busy_timeout = 30000")
    cache_db_local.connection = connection
    cache_db_local.path = CACHE_DB_PATH
    return connection


def initialize_cache_db():
    with open_cache_db() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                namespace TEXT NOT NULL,
                cache_key TEXT NOT NULL,
                payload BLOB,
                expires_at REAL NOT NULL,
                PRIMARY KEY (namespace, cache_key)
            )
            """
        )


def read_cache(namespace, cache_key):
    with cache_lock, open_cache_db() as connection:
        row = connection.execute(
            "SELECT payload, expires_at FROM cache_entries WHERE namespace = ? AND cache_key = ?",
            (namespace, cache_key),
        ).fetchone()
        if row is None:
            return False, None
        if row[1] <= time.time():
            connection.execute(
                "DELETE FROM cache_entries WHERE namespace = ? AND cache_key = ?",
                (namespace, cache_key),
            )
            return False, None
        return True, row[0]


def write_cache(namespace, cache_key, payload, ttl):
    global last_cache_purge_at
    with cache_lock, open_cache_db() as connection:
        monotonic_now = time.monotonic()
        if monotonic_now - last_cache_purge_at >= CACHE_PURGE_INTERVAL:
            connection.execute("DELETE FROM cache_entries WHERE expires_at <= ?", (time.time(),))
            last_cache_purge_at = monotonic_now
        connection.execute(
            """
            INSERT INTO cache_entries (namespace, cache_key, payload, expires_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(namespace, cache_key) DO UPDATE SET
                payload = excluded.payload,
                expires_at = excluded.expires_at
            """,
            (namespace, cache_key, payload, time.time() + ttl),
        )


initialize_cache_db()


def parse_image_size():
    raw_size = request.args.get("size", "64")
    try:
        size = int(raw_size)
    except (TypeError, ValueError):
        raise ValueError("size must be an integer between 16 and 256")
    if not MIN_IMAGE_SIZE <= size <= MAX_IMAGE_SIZE:
        raise ValueError("size must be between 16 and 256")
    return size


def png_response(content):
    etag = hashlib.sha256(content).hexdigest()
    if request.if_none_match.contains(etag):
        response = Response(status=304)
    else:
        response = Response(content, mimetype="image/png")
    response.set_etag(etag)
    response.headers["Content-Length"] = str(len(content))
    response.headers["Cache-Control"] = "public, max-age=31536000"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def resize_png(content, size, silhouette_image=False):
    with Image.open(io.BytesIO(content)) as image:
        image.load()
        image = image.convert("RGBA")
        image.thumbnail((size, size), Image.Resampling.LANCZOS)
        if silhouette_image:
            rgb = image.convert("RGB")
            luminance = rgb.convert("L")
            alpha = luminance.point(lambda value: 255 - value)
            image = Image.new("RGBA", image.size, (0, 0, 0, 0))
            image.putalpha(alpha)
            if image.getchannel("A").getbbox() is None:
                raise ValueError("rasterized silhouette has no visible pixels")
        output = io.BytesIO()
        image.save(output, format="PNG", optimize=True, compress_level=9)
        return output.getvalue()


def silhouette_png(aircraft_type, size):
    cache_key = f"{aircraft_type}:{size}"
    found, cached = read_cache(SILHOUETTE_PNG_CACHE_NAMESPACE, cache_key)
    if found:
        return cached
    source = get_silhouette(aircraft_type)
    if source is None:
        return None
    try:
        svg = source.decode("utf-8")
        svg = re.sub(r"(?i)(fill\s*:\s*)(?:#fff(?:fff)?|white)\b", r"\1#000000", svg)
        svg = re.sub(r"(?i)(fill\s*=\s*[\"'])(?:#fff(?:fff)?|white)([\"'])", r"\1#000000\2", svg)
        tree = usvg.Tree.from_str(svg, usvg.Options.default())
        rasterized = render_svg(
            tree,
            (1, 0, 0, 0, 1, 0),
            bg_color=(255, 255, 255, 255),
        )
        content = resize_png(rasterized, size, silhouette_image=True)
    except (OSError, UnicodeDecodeError, ValueError, RuntimeError) as error:
        app.logger.warning("Silhouette rasterization failed for %s: %s", aircraft_type, error)
        return None
    write_cache(SILHOUETTE_PNG_CACHE_NAMESPACE, cache_key, content, PNG_CACHE_TTL)
    return content


def airline_logo_png(airline_icao, size):
    cache_key = f"{airline_icao}:{size}"
    found, cached = read_cache(AIRLINE_LOGO_PNG_CACHE_NAMESPACE, cache_key)
    if found:
        return cached
    found, source = read_cache(AIRLINE_LOGO_CACHE_NAMESPACE, airline_icao)
    if not found or not source:
        return None
    try:
        content = resize_png(source, size)
    except (OSError, ValueError):
        app.logger.warning("Airline logo rasterization failed for %s", airline_icao)
        return None
    write_cache(AIRLINE_LOGO_PNG_CACHE_NAMESPACE, cache_key, content, PNG_CACHE_TTL)
    return content


def request_adsb(url):
    """Reserve an ADS-B request slot so concurrent sessions stay rate-limited."""
    global last_adsb_request_at
    with adsb_request_lock:
        wait = ADSB_MIN_REQUEST_INTERVAL - (time.monotonic() - last_adsb_request_at)
        if wait > 0:
            time.sleep(wait)
        last_adsb_request_at = time.monotonic()

    return requests.get(
        url,
        headers={"User-Agent": "PlaneRadar/1.0"},
        timeout=REQUEST_TIMEOUT,
    )


def read_adsb_payload_cache(url):
    now = time.monotonic()
    with adsb_payload_cache_lock:
        entry = adsb_payload_cache.get(url)
        if entry is None:
            return None
        expires_at, payload = entry
        if expires_at <= now:
            del adsb_payload_cache[url]
            return None
        return payload


def write_adsb_payload_cache(url, payload):
    now = time.monotonic()
    with adsb_payload_cache_lock:
        for stored_url, (expires_at, _payload) in list(adsb_payload_cache.items()):
            if expires_at <= now:
                del adsb_payload_cache[stored_url]
        adsb_payload_cache[url] = (now + ADSB_PAYLOAD_CACHE_TTL, payload)


def fetch_adsb_payload(latitude, longitude, distance):
    """Return the adsb.fi payload, reusing a short-lived copy for identical queries."""
    url = API_BASE_URL.format(
        lat=f"{latitude:.6f}",
        lon=f"{longitude:.6f}",
        distance=f"{distance:g}",
    )
    cached_payload = read_adsb_payload_cache(url)
    if cached_payload is not None:
        return cached_payload
    response = request_adsb(url)
    response.raise_for_status()
    payload = response.json()
    write_adsb_payload_cache(url, payload)
    return payload


def register_presence(client_id):
    now = time.monotonic()
    with presence_lock:
        cutoff = now - PRESENCE_TIMEOUT
        for stored_id, last_seen in list(active_presence.items()):
            if last_seen < cutoff:
                del active_presence[stored_id]
        if client_id in active_presence or len(active_presence) < MAX_PRESENCE_IDS:
            active_presence[client_id] = now
        return len(active_presence)


def reverse_geocode(latitude, longitude, locality_language="pt"):
    cache_key = f"{latitude:.3f}:{longitude:.3f}:{locality_language}"
    found, cached_payload = read_cache(REVERSE_GEOCODE_CACHE_NAMESPACE, cache_key)
    if found:
        return json.loads(cached_payload)

    response = requests.get(
        REVERSE_GEOCODE_API_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "localityLanguage": locality_language,
        },
        headers={"User-Agent": "PlaneRadar/1.0"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    location_data = {
        "city": payload.get("city", ""),
        "principalsubdivision": payload.get(
            "principalSubdivision", payload.get("principalsubdivision", "")
        ),
        "countryname": payload.get("countryName", payload.get("countryname", "")),
    }
    write_cache(
        REVERSE_GEOCODE_CACHE_NAMESPACE,
        cache_key,
        json.dumps(location_data),
        REVERSE_GEOCODE_CACHE_TTL,
    )
    return location_data


def fetch_flight_route(callsign):
    """Return the route dict for callsign, or None when no route exists.

    Raises requests.RequestException or ValueError when the lookup fails.
    """
    found, cached_payload = read_cache("flight_info", callsign)
    if found:
        return json.loads(cached_payload)

    response = requests.get(
        CALLSIGN_API_URL.format(callsign=requests.utils.quote(callsign, safe="")),
        headers={"User-Agent": "PlaneRadar/1.0"},
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()
    route_data = response.json().get("response", {}).get("flightroute")
    if not route_data:
        return None
    route = {
        "callsign": route_data.get("callsign"),
        "callsign_icao": route_data.get("callsign_icao"),
        "callsign_iata": route_data.get("callsign_iata"),
        "airline": route_data.get("airline"),
        "origin": route_data.get("origin"),
        "destination": route_data.get("destination"),
    }
    write_cache("flight_info", callsign, json.dumps(route), FLIGHT_INFO_CACHE_TTL)
    return route


def get_silhouette(aircraft_type):
    found, cached = read_cache("silhouette", aircraft_type)
    if found:
        return cached

    url = (
        "https://raw.githubusercontent.com/plane-watch/pw-silhouettes/main/"
        f"silhouettes/{requests.utils.quote(aircraft_type, safe='')}.svg"
    )
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "PlaneRadar/1.0"},
            timeout=REQUEST_TIMEOUT,
        )
        content = response.content if response.ok else None
    except requests.RequestException as error:
        app.logger.warning("Silhouette lookup failed for %s: %s", aircraft_type, error)
        content = None
    if content is not None and len(content) > MAX_DOWNLOAD_BYTES:
        app.logger.warning("Silhouette for %s exceeds %s bytes", aircraft_type, MAX_DOWNLOAD_BYTES)
        content = None

    write_cache("silhouette", aircraft_type, content, SILHOUETTE_CACHE_TTL)
    return content


def silhouette_urls(aircraft):
    """Return (svg_url, png_url) for aircraft, looking up its silhouette only once."""
    aircraft_type = str(aircraft.get("t", "")).strip().upper()
    if not re.fullmatch(r"[A-Z0-9_-]{2,10}", aircraft_type):
        return None, None
    if get_silhouette(aircraft_type) is None:
        return None, None
    svg_url = url_for("silhouette", aircraft_type=aircraft_type, _external=True)
    png_url = url_for(
        "silhouette",
        aircraft_type=aircraft_type,
        format="png",
        size=64,
        _external=True,
    )
    return svg_url, png_url


def airline_logo_url(route):
    if not AIRLINE_LOGO_API_KEY:
        return None
    airline = route.get("airline") if route else None
    icao = str(airline.get("icao", "")).strip().upper() if isinstance(airline, dict) else ""
    if not re.fullmatch(r"[A-Z0-9]{2,4}", icao):
        return None
    cache_icao = "TVF" if icao == "TRA" else icao
    found, _cached = read_cache(AIRLINE_LOGO_CACHE_NAMESPACE, cache_icao)
    if found:
        return url_for("airline_logo", airline_icao=cache_icao, _external=True)

    logostream_icao = "TVF" if icao == "TRA" else icao
    logo_url = (
        "https://airlines-api.logostream.dev/airlines/icao/"
        f"{requests.utils.quote(logostream_icao, safe='')}"
        "?variant=tail&format=png&radius=9999&loop=false"
    )
    try:
        response = requests.get(
            logo_url,
            params={"key": AIRLINE_LOGO_API_KEY},
            headers={"User-Agent": "PlaneRadar/1.0"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        content = response.content
    except requests.RequestException as error:
        # Never log the exception itself: its message contains the URL with the API key.
        status_code = getattr(getattr(error, "response", None), "status_code", None)
        app.logger.warning(
            "Airline logo lookup failed for %s: %s (HTTP %s)",
            icao,
            type(error).__name__,
            status_code,
        )
        return None
    if len(content) > MAX_DOWNLOAD_BYTES:
        app.logger.warning("Airline logo for %s exceeds %s bytes", icao, MAX_DOWNLOAD_BYTES)
        return None

    write_cache(AIRLINE_LOGO_CACHE_NAMESPACE, cache_icao, content, AIRLINE_LOGO_CACHE_TTL)
    return url_for("airline_logo", airline_icao=cache_icao, _external=True)


def airline_logo_small_link(route):
    airline = route.get("airline") if route else None
    icao = str(airline.get("icao", "")).strip().upper() if isinstance(airline, dict) else ""
    cache_icao = "TVF" if icao == "TRA" else icao
    return url_for("airline_logo", airline_icao=cache_icao, size=64, _external=True)


def airline_logo_small_url(route):
    logo_url = airline_logo_url(route)
    if logo_url is None:
        return None
    return airline_logo_small_link(route)


def startup_settings():
    parser = argparse.ArgumentParser(
        description="Run PlaneRadar with a default tracking location."
    )
    parser.add_argument("latitude", nargs="?", help="Default tracking latitude")
    parser.add_argument("longitude", nargs="?", help="Default tracking longitude")
    parser.add_argument("distance", nargs="?", help="Default tracking distance in NM")
    parser.add_argument("polling", nargs="?", help="Polling interval in seconds (minimum 3)")
    parser.add_argument("airline_logo_api_key", nargs="?", help="Optional airline logo API key")

    args = parser.parse_args(sys.argv[1:])

    values = [args.latitude, args.longitude, args.distance, args.polling]
    if any(value is not None for value in values) and not all(value is not None for value in values):
        parser.error("latitude, longitude, distance and polling must be provided together")

    if all(value is not None for value in values):
        try:
            latitude = float(args.latitude)
            longitude = float(args.longitude)
            distance = float(args.distance)
            polling = float(args.polling)
        except ValueError:
            parser.error("latitude, longitude, distance and polling must be numbers")
        if not -90 <= latitude <= 90:
            parser.error("latitude must be between -90 and 90")
        if not -180 <= longitude <= 180:
            parser.error("longitude must be between -180 and 180")
        if not 0 < distance <= 250:
            parser.error("distance must be greater than 0 and no more than 250 NM")
        if polling < 3:
            parser.error("polling must be at least 3 seconds")
        if not polling.is_integer():
            parser.error("polling must be a whole number of seconds")
        return args.latitude, args.longitude, args.distance, int(polling), args.airline_logo_api_key or ""

    return DEFAULT_LATITUDE, DEFAULT_LONGITUDE, DEFAULT_DISTANCE, DEFAULT_POLLING, AIRLINE_LOGO_API_KEY


if __name__ == "__main__":
    (
        DEFAULT_LATITUDE,
        DEFAULT_LONGITUDE,
        DEFAULT_DISTANCE,
        DEFAULT_POLLING,
        AIRLINE_LOGO_API_KEY,
    ) = startup_settings()


def parse_location_args(source):
    """Read and validate tracker parameters from a query/form mapping."""
    try:
        latitude = float(source.get("lat", DEFAULT_LATITUDE))
        longitude = float(source.get("lon", DEFAULT_LONGITUDE))
        distance = float(source.get("dist", DEFAULT_DISTANCE))
    except (TypeError, ValueError):
        raise ValueError("Latitude, longitude and distance must be numbers.")

    if not -90 <= latitude <= 90:
        raise ValueError("Latitude must be between -90 and 90.")
    if not -180 <= longitude <= 180:
        raise ValueError("Longitude must be between -180 and 180.")
    if not 0 < distance <= 250:
        raise ValueError("Distance must be greater than 0 and no more than 250 NM.")

    return latitude, longitude, distance


@app.get("/")
def index():
    return render_template(
        "index.html",
        defaults={
            "latitude": DEFAULT_LATITUDE,
            "longitude": DEFAULT_LONGITUDE,
            "distance": DEFAULT_DISTANCE,
            "polling": DEFAULT_POLLING,
        },
    )


@app.get("/mobile")
def mobile():
    return render_template(
        "mobile.html",
        defaults={
            "latitude": DEFAULT_LATITUDE,
            "longitude": DEFAULT_LONGITUDE,
            "distance": DEFAULT_DISTANCE,
            "polling": DEFAULT_POLLING,
        },
    )


@app.get("/api/flight-info")
def flight_info():
    callsign = request.args.get("callsign", "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9 ._-]{1,15}", callsign):
        return jsonify({"error": "A valid callsign is required."}), 400

    try:
        route = fetch_flight_route(callsign)
    except requests.HTTPError as error:
        status_code = error.response.status_code if error.response is not None else None
        app.logger.warning("Flight info service returned HTTP %s", status_code)
        return jsonify({"error": "The flight information service is unavailable."}), 502
    except requests.RequestException as error:
        app.logger.warning("Flight info request failed: %s", error)
        return jsonify({"error": "The flight information service is unavailable."}), 502
    except ValueError:
        return jsonify({"error": "The flight information service returned invalid JSON."}), 502

    if route is None:
        return jsonify({"error": "No route information was found for this callsign."}), 404
    return jsonify(route)


@app.get("/api/aircraft")
def aircraft():
    try:
        latitude, longitude, distance = parse_location_args(request.args)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    try:
        payload = fetch_adsb_payload(latitude, longitude, distance)
    except requests.HTTPError as error:
        status_code = error.response.status_code if error.response is not None else 502
        if status_code == 429:
            return jsonify(
                {"error": "The ADS-B service rate limit was reached. Please try again shortly."}
            ), 429
        if status_code in (400, 401, 403, 404):
            return jsonify({"error": "The ADS-B service rejected this request."}), 502
        app.logger.warning("ADS-B service returned HTTP %s", status_code)
        return jsonify({"error": "The ADS-B service is temporarily unavailable."}), 502
    except requests.RequestException as error:
        app.logger.warning("ADS-B request failed: %s", error)
        return jsonify({"error": "The ADS-B service is temporarily unavailable."}), 502
    except ValueError:
        return jsonify({"error": "The ADS-B service returned invalid JSON."}), 502

    return jsonify(
        {
            "aircraft": payload.get("ac", []),
            "total": payload.get("total", len(payload.get("ac", []))),
            "now": payload.get("now"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "location": {
                "latitude": latitude,
                "longitude": longitude,
                "distance": distance,
            },
        }
    )


@app.get("/api/nearest-aircraft")
def nearest_aircraft():
    try:
        latitude, longitude, distance = parse_location_args(request.args)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    try:
        payload = fetch_adsb_payload(latitude, longitude, distance)
    except requests.HTTPError as error:
        status_code = error.response.status_code if error.response is not None else 502
        if status_code == 429:
            return jsonify({"error": "The ADS-B service rate limit was reached. Please try again shortly."}), 429
        return jsonify({"error": "The ADS-B service rejected this request." if status_code in (400, 401, 403, 404) else "The ADS-B service is temporarily unavailable."}), 502
    except requests.RequestException as error:
        app.logger.warning("Nearest ADS-B request failed: %s", error)
        return jsonify({"error": "The ADS-B service is temporarily unavailable."}), 502
    except ValueError:
        return jsonify({"error": "The ADS-B service returned invalid JSON."}), 502

    aircraft_list = payload.get("ac", [])
    location_data = {"latitude": latitude, "longitude": longitude, "distance": distance}
    try:
        location_data.update(reverse_geocode(latitude, longitude))
    except (requests.RequestException, ValueError) as error:
        app.logger.warning("Nearest location lookup failed: %s", error)
    nearest = min(
        aircraft_list,
        key=lambda item: float(item.get("dst")) if item.get("dst") is not None else float("inf"),
        default=None,
    )
    if nearest is None:
        return jsonify({
            "aircraft": None,
            "flight_info": None,
            "airline_logo": None,
            "silhouette": None,
            "silhouette_png": None,
            "airline_logo_small": None,
            "location": location_data,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        })
    callsign = str(nearest.get("flight", "")).strip().upper()
    route = None
    if callsign:
        try:
            route = fetch_flight_route(callsign)
        except (requests.RequestException, ValueError):
            app.logger.warning("Nearest flight info unavailable for %s", callsign)

    logo_url = airline_logo_url(route)
    silhouette_svg_url, silhouette_png_url = silhouette_urls(nearest)
    return jsonify({
        "aircraft": nearest,
        "flight_info": route,
        "airline_logo": logo_url,
        "silhouette": silhouette_svg_url,
        "silhouette_png": silhouette_png_url,
        "airline_logo_small": airline_logo_small_link(route) if logo_url is not None else None,
        "location": location_data,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    })


@app.post("/api/presence")
def presence():
    payload = request.get_json(silent=True) or {}
    client_id = payload.get("client_id")
    if not isinstance(client_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,100}", client_id):
        return jsonify({"error": "A valid client identifier is required."}), 400
    return jsonify({"active_users": register_presence(client_id)})


@app.get("/api/silhouette/<aircraft_type>")
def silhouette(aircraft_type):
    normalized_type = aircraft_type.strip().upper()
    if normalized_type.endswith(".SVG"):
        normalized_type = normalized_type[:-4]
    if not re.fullmatch(r"[A-Z0-9_-]{2,10}", normalized_type):
        return jsonify({"error": "Invalid aircraft type."}), 400
    output_format = request.args.get("format", "").lower()
    if output_format == "png":
        try:
            size = parse_image_size()
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        content = silhouette_png(normalized_type, size)
        if content is None:
            return jsonify({"error": "Silhouette not found or could not be rasterized."}), 404
        return png_response(content)
    if output_format:
        return jsonify({"error": "format must be png."}), 400
    content = get_silhouette(normalized_type)
    if content is None:
        return jsonify({"error": "Silhouette not found."}), 404
    return Response(
        content,
        mimetype="image/svg+xml",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Security-Policy": SVG_CONTENT_SECURITY_POLICY,
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/airline-logo/<airline_icao>")
def airline_logo(airline_icao):
    normalized_icao = airline_icao.strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{2,4}", normalized_icao):
        return jsonify({"error": "Invalid airline ICAO."}), 400
    normalized_icao = "TVF" if normalized_icao == "TRA" else normalized_icao
    if "size" in request.args:
        try:
            size = parse_image_size()
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        content = airline_logo_png(normalized_icao, size)
        if content is None:
            return jsonify({"error": "Airline logo not found or could not be rasterized."}), 404
        return png_response(content)
    found, content = read_cache(AIRLINE_LOGO_CACHE_NAMESPACE, normalized_icao)
    if not found or not content:
        return jsonify({"error": "Airline logo not found."}), 404
    return Response(
        content,
        mimetype="image/png",
        headers={"Cache-Control": "public, max-age=604800", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/location")
def location():
    try:
        latitude = float(request.args["lat"])
        longitude = float(request.args["lon"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "Latitude and longitude must be numbers."}), 400

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return jsonify({"error": "Latitude or longitude is out of range."}), 400

    locality_language = request.args.get("localityLanguage", "en").lower()
    if locality_language not in {"pt", "en"}:
        return jsonify({"error": "localityLanguage must be pt or en."}), 400

    try:
        location_data = reverse_geocode(latitude, longitude, locality_language)
    except requests.RequestException as error:
        app.logger.warning("Reverse geocoding request failed: %s", error)
        return jsonify({"error": "The location service is temporarily unavailable."}), 502
    except ValueError:
        return jsonify({"error": "The location service returned invalid JSON."}), 502

    return jsonify(location_data)

if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "").lower() == "true",
    )
