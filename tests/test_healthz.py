import os
import tempfile
import unittest

cache_directory = tempfile.mkdtemp(prefix="planeradar-tests-")
os.environ["PLANE_RADAR_CACHE_DB"] = os.path.join(cache_directory, "cache.sqlite3")
from app import app


class HealthzTests(unittest.TestCase):
    def test_healthz_returns_ok_without_external_calls(self):
        client = app.test_client()
        response = client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "ok")
        self.assertTrue(response.content_type.startswith("text/plain"))


if __name__ == "__main__":
    unittest.main()
