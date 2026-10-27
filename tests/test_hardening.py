import os
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

cache_directory = tempfile.mkdtemp(prefix="planeradar-tests-")
os.environ["PLANE_RADAR_CACHE_DB"] = os.path.join(cache_directory, "cache.sqlite3")
import requests
from app import app
import app as app_module


class HardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def setUp(self):
        app_module.AIRLINE_LOGO_API_KEY = "SECRET-TEST-KEY"

    @patch("app.get_silhouette")
    def test_silhouette_svg_has_csp_and_nosniff(self, get_silhouette):
        get_silhouette.return_value = b'<svg xmlns="http://www.w3.org/2000/svg"/>'

        response = self.client.get("/api/silhouette/A320")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith("image/svg+xml"))
        self.assertEqual(
            response.headers["Content-Security-Policy"],
            "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
        )
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_png_response_has_nosniff(self):
        with app.test_request_context("/"):
            response = app_module.png_response(b"\x89PNG\r\n\x1a\n")

        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.content_type, "image/png")

    @patch("app.read_cache", return_value=(True, b"\x89PNG\r\n\x1a\n"))
    def test_original_airline_logo_has_nosniff(self, _read_cache):
        response = self.client.get("/api/airline-logo/TST")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    @patch("app.write_cache")
    @patch("app.read_cache", return_value=(False, None))
    @patch("app.requests.get")
    def test_airline_logo_sends_key_in_params_and_logs_no_key(
        self, requests_get, _read_cache, _write_cache
    ):
        response = Mock()
        response.content = b"logo"
        response.raise_for_status.return_value = None
        requests_get.return_value = response

        with app.test_request_context("/"):
            app_module.airline_logo_url({"airline": {"icao": "ABC"}})

        self.assertEqual(requests_get.call_args.kwargs["params"], {"key": "SECRET-TEST-KEY"})
        self.assertNotIn("SECRET-TEST-KEY", requests_get.call_args.args[0])

    @patch("app.write_cache")
    @patch("app.read_cache", return_value=(False, None))
    @patch("app.requests.get")
    def test_airline_logo_failure_logs_only_type_and_status(
        self, requests_get, _read_cache, _write_cache
    ):
        error_response = Mock(status_code=503)
        error = requests.HTTPError(
            "503 Server Error for url: https://airlines-api.logostream.dev/x?key=SECRET-TEST-KEY",
            response=error_response,
        )
        failing = Mock()
        failing.raise_for_status.side_effect = error
        requests_get.return_value = failing

        with patch.object(app_module.app.logger, "warning") as warning:
            with app.test_request_context("/"):
                result = app_module.airline_logo_url({"airline": {"icao": "ABC"}})

        self.assertIsNone(result)
        logged = " ".join(str(part) for part in warning.call_args.args)
        self.assertNotIn("SECRET-TEST-KEY", logged)
        self.assertNotIn("logostream", logged)
        self.assertIn("HTTPError", logged)
        self.assertIn("503", logged)

    @patch("app.write_cache")
    @patch("app.read_cache", return_value=(False, None))
    @patch("app.requests.get")
    def test_airline_logo_connection_error_does_not_log_url(
        self, requests_get, _read_cache, _write_cache
    ):
        requests_get.side_effect = requests.ConnectionError(
            "failed: https://airlines-api.logostream.dev/x?key=SECRET-TEST-KEY"
        )

        with patch.object(app_module.app.logger, "warning") as warning:
            with app.test_request_context("/"):
                result = app_module.airline_logo_url({"airline": {"icao": "ABC"}})

        self.assertIsNone(result)
        logged = " ".join(str(part) for part in warning.call_args.args)
        self.assertNotIn("SECRET-TEST-KEY", logged)
        self.assertIn("ConnectionError", logged)

    def test_register_presence_caps_new_ids(self):
        now = time.monotonic()
        full = {f"client-{index:05d}-abcdef": now for index in range(app_module.MAX_PRESENCE_IDS)}
        with patch.dict(app_module.active_presence, full, clear=True):
            count = app_module.register_presence("new-client-0000000001")

            self.assertEqual(count, app_module.MAX_PRESENCE_IDS)
            self.assertNotIn("new-client-0000000001", app_module.active_presence)
            self.assertEqual(len(app_module.active_presence), app_module.MAX_PRESENCE_IDS)

    def test_register_presence_refreshes_existing_id_when_full(self):
        now = time.monotonic()
        full = {f"client-{index:05d}-abcdef": now for index in range(app_module.MAX_PRESENCE_IDS)}
        with patch.dict(app_module.active_presence, full, clear=True):
            known_id = "client-00007-abcdef"
            app_module.active_presence[known_id] = now - 10

            count = app_module.register_presence(known_id)

            self.assertEqual(count, app_module.MAX_PRESENCE_IDS)
            self.assertGreater(app_module.active_presence[known_id], now - 1)

    def test_register_presence_accepts_new_id_after_expired_entries_are_pruned(self):
        stale = time.monotonic() - app_module.PRESENCE_TIMEOUT - 1
        full = {f"stale-{index:05d}-abcdef": stale for index in range(app_module.MAX_PRESENCE_IDS)}
        with patch.dict(app_module.active_presence, full, clear=True):
            count = app_module.register_presence("new-client-0000000002")

            self.assertEqual(count, 1)
            self.assertIn("new-client-0000000002", app_module.active_presence)


if __name__ == "__main__":
    unittest.main()
