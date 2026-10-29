import copy
import math
import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("PLANE_RADAR_CACHE_DB", os.path.join(tempfile.mkdtemp(prefix="planeradar-tests-"), "cache.sqlite3"))
import requests
from app import app
import app as app_module


def close_thread_cache_connection():
    connection = getattr(app_module.cache_db_local, "connection", None)
    if connection is not None:
        connection.close()
        app_module.cache_db_local.connection = None


def adsb_response(aircraft):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"ac": aircraft, "total": len(aircraft), "now": 1}
    return response


class AdsbPayloadCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def setUp(self):
        app_module.adsb_payload_cache.clear()
        self.addCleanup(app_module.adsb_payload_cache.clear)

    @patch("app.request_adsb")
    def test_aircraft_payload_is_reused_within_ttl(self, request_adsb):
        request_adsb.return_value = adsb_response([{"hex": "abc123"}])

        first = self.client.get("/api/aircraft?lat=1&lon=2&dist=3")
        second = self.client.get("/api/aircraft?lat=1&lon=2&dist=3")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()["aircraft"], [{"hex": "abc123"}])
        self.assertEqual(request_adsb.call_count, 1)

    @patch("app.request_adsb")
    def test_different_queries_are_not_shared(self, request_adsb):
        request_adsb.return_value = adsb_response([])

        self.client.get("/api/aircraft?lat=1&lon=2&dist=3")
        self.client.get("/api/aircraft?lat=1&lon=2&dist=4")

        self.assertEqual(request_adsb.call_count, 2)

    @patch("app.ADSB_PAYLOAD_CACHE_TTL", 0)
    @patch("app.request_adsb")
    def test_aircraft_payload_is_refetched_after_ttl(self, request_adsb):
        request_adsb.return_value = adsb_response([])

        self.client.get("/api/aircraft?lat=1&lon=2&dist=3")
        self.client.get("/api/aircraft?lat=1&lon=2&dist=3")

        self.assertEqual(request_adsb.call_count, 2)

    @patch("app.request_adsb")
    def test_nearest_aircraft_shares_cached_payload_with_aircraft(self, request_adsb):
        request_adsb.return_value = adsb_response([{"hex": "abc123", "dst": 1}])

        with patch("app.reverse_geocode", return_value={}):
            self.client.get("/api/aircraft?lat=1&lon=2&dist=3")
            nearest = self.client.get("/api/nearest-aircraft?lat=1&lon=2&dist=3")

        self.assertEqual(nearest.status_code, 200)
        self.assertEqual(nearest.get_json()["aircraft"]["hex"], "abc123")
        self.assertEqual(request_adsb.call_count, 1)

    @patch("app.request_adsb")
    def test_errors_are_not_cached(self, request_adsb):
        error_response = Mock(status_code=500)
        failing = Mock()
        failing.raise_for_status.side_effect = requests.HTTPError("500", response=error_response)
        request_adsb.side_effect = [failing, adsb_response([])]

        first = self.client.get("/api/aircraft?lat=1&lon=2&dist=3")
        second = self.client.get("/api/aircraft?lat=1&lon=2&dist=3")

        self.assertEqual(first.status_code, 502)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(request_adsb.call_count, 2)

    def test_write_discards_expired_entries(self):
        stale_url = "https://example.invalid/stale"
        app_module.adsb_payload_cache[stale_url] = (time.monotonic() - 1, {"ac": []})

        app_module.write_adsb_payload_cache("https://example.invalid/fresh", {"ac": []})

        self.assertNotIn(stale_url, app_module.adsb_payload_cache)
        self.assertIn("https://example.invalid/fresh", app_module.adsb_payload_cache)


def expected_nm(latitude1, longitude1, latitude2, longitude2):
    phi1, phi2 = math.radians(latitude1), math.radians(latitude2)
    delta_phi = phi2 - phi1
    delta_lambda = math.radians(longitude2 - longitude1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(a))


class AdsbCoordinateSharingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def setUp(self):
        app_module.adsb_payload_cache.clear()
        self.addCleanup(app_module.adsb_payload_cache.clear)

    @patch("app.request_adsb")
    def test_nearby_coordinates_share_one_upstream_request(self, request_adsb):
        request_adsb.return_value = adsb_response([])

        first = self.client.get("/api/aircraft?lat=-21.80568&lon=-48.13961&dist=25")
        second = self.client.get("/api/aircraft?lat=-21.80562&lon=-48.13957&dist=25")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(request_adsb.call_count, 1)
        self.assertIn("/lat/-21.806/lon/-48.140/dist/25.05", request_adsb.call_args.args[0])

    @patch("app.request_adsb")
    def test_radius_is_capped_at_maximum_distance(self, request_adsb):
        request_adsb.return_value = adsb_response([])

        response = self.client.get("/api/aircraft?lat=1&lon=2&dist=250")

        self.assertEqual(response.status_code, 200)
        self.assertIn("/dist/250", request_adsb.call_args.args[0])

    @patch("app.request_adsb")
    def test_distance_is_recalculated_from_exact_user_position(self, request_adsb):
        # Aircraft 0.1 degrees north of both users, so the distance depends on each exact position.
        aircraft_lat = -21.80568 + 0.1
        aircraft_lon = -48.13961
        request_adsb.return_value = adsb_response(
            [{"hex": "abc123", "lat": aircraft_lat, "lon": aircraft_lon, "dst": 99, "dir": 0}]
        )

        first = self.client.get("/api/aircraft?lat=-21.80568&lon=-48.13961&dist=25")
        second = self.client.get("/api/aircraft?lat=-21.80562&lon=-48.13957&dist=25")

        self.assertEqual(request_adsb.call_count, 1)
        first_aircraft = first.get_json()["aircraft"][0]
        second_aircraft = second.get_json()["aircraft"][0]
        self.assertAlmostEqual(
            first_aircraft["dst"], round(expected_nm(-21.80568, -48.13961, aircraft_lat, aircraft_lon), 3), places=3
        )
        self.assertAlmostEqual(
            second_aircraft["dst"], round(expected_nm(-21.80562, -48.13957, aircraft_lat, aircraft_lon), 3), places=3
        )
        self.assertNotEqual(first_aircraft["dst"], second_aircraft["dst"])
        self.assertAlmostEqual(first_aircraft["dir"], 0, places=1)

    @patch("app.request_adsb")
    def test_aircraft_outside_original_radius_is_filtered(self, request_adsb):
        request_adsb.return_value = adsb_response(
            [
                {"hex": "inside", "lat": 0.1, "lon": 0.0, "dst": 6.0},
                {"hex": "outside_margin", "lat": 0.17, "lon": 0.0, "dst": 10.1},
                {"hex": "no_position", "flight": "NOPOS"},
            ]
        )

        response = self.client.get("/api/aircraft?lat=0&lon=0&dist=10")

        hexes = [item["hex"] for item in response.get_json()["aircraft"]]
        self.assertEqual(hexes, ["inside", "no_position"])
        self.assertEqual(response.get_json()["total"], 2)

    @patch("app.request_adsb")
    def test_cached_upstream_payload_is_not_mutated(self, request_adsb):
        upstream = {
            "ac": [
                {"hex": "inside", "lat": 0.1, "lon": 0.0, "dst": 99, "dir": 0},
                {"hex": "outside", "lat": 0.5, "lon": 0.0, "dst": 98},
            ],
            "total": 2,
            "now": 1,
        }
        original = copy.deepcopy(upstream)
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = upstream
        request_adsb.return_value = response

        first = self.client.get("/api/aircraft?lat=0&lon=0&dist=10")
        second = self.client.get("/api/aircraft?lat=0.00004&lon=0&dist=10")

        self.assertEqual(request_adsb.call_count, 1)
        self.assertEqual(first.get_json()["aircraft"][0]["hex"], "inside")
        self.assertEqual(second.get_json()["aircraft"][0]["hex"], "inside")
        self.assertEqual(len(second.get_json()["aircraft"]), 1)
        cached_payload = app_module.adsb_payload_cache[next(iter(app_module.adsb_payload_cache))][1]
        self.assertEqual(cached_payload, original)
        self.assertEqual(upstream, original)


class ReverseGeocodeCacheTests(unittest.TestCase):
    def setUp(self):
        temp_directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp_directory.cleanup)
        patcher = patch.object(
            app_module, "CACHE_DB_PATH", os.path.join(temp_directory.name, "cache.sqlite3")
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(close_thread_cache_connection)
        app_module.initialize_cache_db()

    @staticmethod
    def geocode_response():
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "city": "Araraquara",
            "principalSubdivision": "Sao Paulo",
            "countryName": "Brazil",
        }
        return response

    @patch("app.requests.get")
    def test_reverse_geocode_is_cached_by_rounded_coordinates(self, requests_get):
        requests_get.return_value = self.geocode_response()

        first = app_module.reverse_geocode(-21.805684, -48.139653, "pt")
        second = app_module.reverse_geocode(-21.80562, -48.13964, "pt")

        self.assertEqual(
            first,
            {"city": "Araraquara", "principalsubdivision": "Sao Paulo", "countryname": "Brazil"},
        )
        self.assertEqual(second, first)
        self.assertEqual(requests_get.call_count, 1)

    @patch("app.requests.get")
    def test_reverse_geocode_cache_key_includes_language(self, requests_get):
        requests_get.return_value = self.geocode_response()

        app_module.reverse_geocode(-21.805684, -48.139653, "pt")
        app_module.reverse_geocode(-21.805684, -48.139653, "en")

        self.assertEqual(requests_get.call_count, 2)
        self.assertEqual(requests_get.call_args.kwargs["params"]["localityLanguage"], "en")

    @patch("app.requests.get")
    def test_reverse_geocode_errors_are_not_cached(self, requests_get):
        requests_get.side_effect = requests.ConnectionError("unavailable")

        with self.assertRaises(requests.ConnectionError):
            app_module.reverse_geocode(-21.805684, -48.139653, "pt")
        with self.assertRaises(requests.ConnectionError):
            app_module.reverse_geocode(-21.805684, -48.139653, "pt")

        self.assertEqual(requests_get.call_count, 2)

    def test_reverse_geocode_ttl_is_one_day(self):
        self.assertEqual(app_module.REVERSE_GEOCODE_CACHE_TTL, 86400)


class SqliteConnectionTests(unittest.TestCase):
    def setUp(self):
        temp_directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(temp_directory.cleanup)
        self.first_path = os.path.join(temp_directory.name, "first.sqlite3")
        self.second_path = os.path.join(temp_directory.name, "second.sqlite3")
        patcher = patch.object(app_module, "CACHE_DB_PATH", self.first_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(close_thread_cache_connection)

    def test_connection_is_reused_within_a_thread(self):
        self.assertIs(app_module.open_cache_db(), app_module.open_cache_db())

    def test_connection_reopens_when_cache_path_changes(self):
        first = app_module.open_cache_db()
        with patch.object(app_module, "CACHE_DB_PATH", self.second_path):
            second = app_module.open_cache_db()

        self.assertIsNot(first, second)
        self.assertTrue(os.path.exists(self.second_path))

    def test_write_is_committed_and_visible_to_read(self):
        app_module.initialize_cache_db()
        app_module.write_cache("test_namespace", "key", b"value", 60)

        close_thread_cache_connection()
        found, payload = app_module.read_cache("test_namespace", "key")

        self.assertTrue(found)
        self.assertEqual(bytes(payload), b"value")


if __name__ == "__main__":
    unittest.main()
