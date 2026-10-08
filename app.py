import argparse
import os
import re
import sys
import time
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

API_BASE_URL = "https://opendata.adsb.fi/api/v3/lat/{lat}/lon/{lon}/dist/{distance}"
CALLSIGN_API_URL = "https://api.adsbdb.com/v0/callsign/{callsign}"
REVERSE_GEOCODE_API_URL = "https://api-bdc.io/data/reverse-geocode-client"
DEFAULT_LATITUDE = os.getenv("PLANE_RADAR_LAT", "-21.805684")
DEFAULT_LONGITUDE = os.getenv("PLANE_RADAR_LON", "-48.139653")
DEFAULT_DISTANCE = os.getenv("PLANE_RADAR_DISTANCE", "25")
DEFAULT_POLLING = int(os.getenv("PLANE_RADAR_POLLING", "10"))
REQUEST_TIMEOUT = 12
FLIGHT_INFO_CACHE_TTL = 900
flight_info_cache = {}


def startup_settings():
    parser = argparse.ArgumentParser(
        description="Run PlaneRadar with a default tracking location."
    )
    parser.add_argument("latitude", nargs="?", help="Default tracking latitude")
    parser.add_argument("longitude", nargs="?", help="Default tracking longitude")
    parser.add_argument("distance", nargs="?", help="Default tracking distance in NM")
    parser.add_argument("polling", nargs="?", help="Polling interval in seconds (minimum 3)")

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
        return args.latitude, args.longitude, args.distance, int(polling)

    return DEFAULT_LATITUDE, DEFAULT_LONGITUDE, DEFAULT_DISTANCE, DEFAULT_POLLING


if __name__ == "__main__":
    (
        DEFAULT_LATITUDE,
        DEFAULT_LONGITUDE,
        DEFAULT_DISTANCE,
        DEFAULT_POLLING,
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

    cached = flight_info_cache.get(callsign)
    if cached and time.monotonic() - cached["cached_at"] < FLIGHT_INFO_CACHE_TTL:
        return jsonify(cached["payload"])

    url = CALLSIGN_API_URL.format(callsign=requests.utils.quote(callsign, safe=""))
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "PlaneRadar/1.0"},
            timeout=REQUEST_TIMEOUT,
        )
        if response.status_code == 404:
            return jsonify({"error": "No route information was found for this callsign."}), 404
        response.raise_for_status()
        payload = response.json()
        route = payload.get("response", {}).get("flightroute")
        if not route:
            return jsonify({"error": "No route information was found for this callsign."}), 404
    except requests.HTTPError:
        app.logger.warning("Flight info service returned HTTP %s", response.status_code)
        return jsonify({"error": "The flight information service is unavailable."}), 502
    except requests.RequestException as error:
        app.logger.warning("Flight info request failed: %s", error)
        return jsonify({"error": "The flight information service is unavailable."}), 502
    except ValueError:
        return jsonify({"error": "The flight information service returned invalid JSON."}), 502

    result = {
        "callsign": route.get("callsign"),
        "callsign_icao": route.get("callsign_icao"),
        "callsign_iata": route.get("callsign_iata"),
        "airline": route.get("airline"),
        "origin": route.get("origin"),
        "destination": route.get("destination"),
    }
    flight_info_cache[callsign] = {"cached_at": time.monotonic(), "payload": result}
    return jsonify(result)


@app.get("/api/aircraft")
def aircraft():
    try:
        latitude, longitude, distance = parse_location_args(request.args)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    url = API_BASE_URL.format(
        lat=f"{latitude:.6f}",
        lon=f"{longitude:.6f}",
        distance=f"{distance:g}",
    )

    try:
        response = requests.get(
            url,
            headers={"User-Agent": "PlaneRadar/1.0"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
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
    except requests.RequestException as error:
        app.logger.warning("Reverse geocoding request failed: %s", error)
        return jsonify({"error": "The location service is temporarily unavailable."}), 502
    except ValueError:
        return jsonify({"error": "The location service returned invalid JSON."}), 502

    return jsonify(
        {
            "city": payload.get("city", ""),
            "principalsubdivision": payload.get("principalSubdivision", payload.get("principalsubdivision", "")),
            "countryname": payload.get("countryName", payload.get("countryname", "")),
        }
    )

if __name__ == "__main__":
    app.run(
        host=os.getenv("FLASK_HOST", "0.0.0.0"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "").lower() == "true",
    )
