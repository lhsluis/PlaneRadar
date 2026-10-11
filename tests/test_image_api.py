import io
import json
import os
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

cache_directory = tempfile.mkdtemp(prefix="planeradar-tests-")
os.environ["PLANE_RADAR_CACHE_DB"] = os.path.join(cache_directory, "cache.sqlite3")
from app import (
    AIRLINE_LOGO_CACHE_NAMESPACE,
    FLIGHT_INFO_CACHE_TTL,
    app,
    write_cache,
)
import app as app_module


class ImageApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def setUp(self):
        app_module.AIRLINE_LOGO_API_KEY = "test-key"

    @staticmethod
    def png_metadata(content):
        assert content[:8] == b"\x89PNG\r\n\x1a\n"
        width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
            ">IIBBBBB", content[16:29]
        )
        return width, height, bit_depth, color_type, interlace

    @patch("app.get_silhouette")
    def test_silhouette_png_is_rgba_non_interlaced_and_cached(self, get_silhouette):
        get_silhouette.return_value = (
            b'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="100">'
            b'<rect width="200" height="100" fill="red"/></svg>'
        )

        response = self.client.get("/api/silhouette/A320?format=png&size=64")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "image/png")
        self.assertLessEqual(len(response.data), 5 * 1024)
        self.assertEqual(self.png_metadata(response.data), (64, 32, 8, 6, 0))
        self.assertEqual(response.headers["Content-Length"], str(len(response.data)))
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=31536000")

        cached_response = self.client.get(
            "/api/silhouette/A320?format=png&size=64",
            headers={"If-None-Match": response.headers["ETag"]},
        )
        self.assertEqual(cached_response.status_code, 304)
        self.assertEqual(cached_response.headers["ETag"], response.headers["ETag"])
        get_silhouette.assert_called_once_with("A320")

    @patch("app.get_silhouette", return_value=None)
    def test_unknown_silhouette_is_not_rasterized(self, get_silhouette):
        response = self.client.get("/api/silhouette/UNKNOWN?format=png&size=64")

        self.assertEqual(response.status_code, 404)
        get_silhouette.assert_called_once_with("UNKNOWN")

    def test_airline_logo_png_is_resized_and_has_expected_headers(self):
        source = io.BytesIO()
        from PIL import Image

        Image.new("RGBA", (128, 64), (0, 0, 0, 128)).save(source, format="PNG")
        write_cache(AIRLINE_LOGO_CACHE_NAMESPACE, "TST", source.getvalue(), 3600)

        response = self.client.get("/api/airline-logo/TST?size=64")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.png_metadata(response.data), (64, 32, 8, 6, 0))
        self.assertLessEqual(len(response.data), 8 * 1024)

    @patch("app.reverse_geocode", return_value={})
    @patch("app.request_adsb")
    def test_nearest_aircraft_includes_small_urls_with_forwarded_host(self, request_adsb, _reverse_geocode):
        adsb_response = Mock()
        adsb_response.raise_for_status.return_value = None
        adsb_response.json.return_value = {
            "ac": [{"hex": "abc123", "flight": "TST123", "t": "A320", "dst": 1}]
        }
        request_adsb.return_value = adsb_response
        route = {
            "airline": {"icao": "TST"},
            "callsign": "TST123",
            "origin": None,
            "destination": None,
        }
        write_cache("flight_info", "TST123", json.dumps(route), FLIGHT_INFO_CACHE_TTL)
        write_cache(
            AIRLINE_LOGO_CACHE_NAMESPACE,
            "TST",
            b"\x89PNG\r\n\x1a\n",
            3600,
        )

        with patch("app.get_silhouette", return_value=b'<svg xmlns="http://www.w3.org/2000/svg"/>'):
            response = self.client.get(
                "/api/nearest-aircraft?lat=1&lon=2&dist=3",
                headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "radar.example"},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(
            payload["silhouette_png"],
            "https://radar.example/api/silhouette/A320?format=png&size=64",
        )
        self.assertEqual(
            payload["airline_logo_small"],
            "https://radar.example/api/airline-logo/TST?size=64",
        )


if __name__ == "__main__":
    unittest.main()
