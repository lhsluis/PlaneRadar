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
