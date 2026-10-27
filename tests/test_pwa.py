import json
import os
import tempfile
import unittest

cache_directory = tempfile.mkdtemp(prefix="planeradar-tests-")
os.environ["PLANE_RADAR_CACHE_DB"] = os.path.join(cache_directory, "cache.sqlite3")
from app import app


class PwaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = app.test_client()

    def test_service_worker_served_at_root(self):
        response = self.client.get("/sw.js")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith("application/javascript"))
        self.assertEqual(response.headers["Service-Worker-Allowed"], "/")
        self.assertEqual(response.headers["Cache-Control"], "no-cache")

    def test_manifest_served_with_manifest_mimetype(self):
        response = self.client.get("/manifest.webmanifest")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content_type, "application/manifest+json")
        manifest = json.loads(response.get_data(as_text=True))
        self.assertEqual(manifest["name"], "PlaneRadar")
        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["display"], "standalone")
        purposes = {icon["purpose"] for icon in manifest["icons"]}
        self.assertIn("any", purposes)
        self.assertIn("maskable", purposes)

    def test_pages_link_manifest_and_ios_meta(self):
        for path in ("/", "/mobile"):
            with self.subTest(path=path):
                response = self.client.get(path)
                html = response.get_data(as_text=True)

                self.assertEqual(response.status_code, 200)
                self.assertIn('rel="manifest" href="/manifest.webmanifest"', html)
                self.assertIn('name="apple-mobile-web-app-capable" content="yes"', html)
                self.assertIn('name="apple-mobile-web-app-status-bar-style" content="black-translucent"', html)
                self.assertIn("viewport-fit=cover", html)
                self.assertIn("/static/pwa.js", html)


if __name__ == "__main__":
    unittest.main()
