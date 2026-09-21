from __future__ import annotations

import importlib
import json
import sys
import threading
import unittest
from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

library = importlib.import_module("infinito_docs.library")
server = importlib.import_module("infinito_docs.server")

SCRIPT = (
    PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "javascript" / "versions.js"
)


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = TemporaryDirectory()
        data = Path(cls._tmp.name)
        cls.library = library.Library("unused", data, 1, data)
        cls.library.refs = lambda: ("abc123", ["v1.0.0"])
        site = data / "sites" / "latest"
        (site / "html" / "docs").mkdir(parents=True)
        (site / "html" / "index.html").write_text("root", encoding="utf-8")
        (site / "html" / "page.html").write_text("page", encoding="utf-8")
        (site / "html" / "docs" / "index.html").write_text("docs", encoding="utf-8")
        (site / "ref").write_text("abc123", encoding="utf-8")
        (data / "secret.txt").write_text("secret", encoding="utf-8")

        cls._script = patch.object(server, "SCRIPT", SCRIPT)
        cls._script.start()
        cls.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(server.DocsHandler, library=cls.library)
        )
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls._script.stop()
        cls._tmp.cleanup()

    def _request(self, path, method="GET"):
        connection = HTTPConnection(
            "127.0.0.1", self.httpd.server_address[1], timeout=5
        )
        connection.request(method, path)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        connection.close()
        return response.status, response.getheader("Location"), body

    def test_root_redirects_to_the_latest_commit(self) -> None:
        self.assertEqual(self._request("/")[:2], (302, "/latest/"))

    def test_version_without_slash_gains_one(self) -> None:
        self.assertEqual(self._request("/latest")[:2], (302, "/latest/"))

    def test_built_files_are_served(self) -> None:
        self.assertEqual(self._request("/latest/"), (200, None, "root"))
        self.assertEqual(self._request("/latest/page.html"), (200, None, "page"))
        self.assertEqual(self._request("/latest/docs/"), (200, None, "docs"))

    def test_directory_without_slash_gains_one(self) -> None:
        self.assertEqual(self._request("/latest/docs")[:2], (302, "/latest/docs/"))

    def test_page_missing_in_a_version_falls_back_to_its_start_page(self) -> None:
        self.assertEqual(self._request("/latest/gone.html")[:2], (302, "/latest/"))

    def test_paths_cannot_leave_the_site(self) -> None:
        self.assertTrue(
            (self.library.sites / "latest" / "html" / "../../../secret.txt")
            .resolve()
            .is_file()
        )
        for path in (
            "/latest/../../../secret.txt",
            "/latest/%2e%2e/%2e%2e/%2e%2e/secret.txt",
        ):
            status, location, body = self._request(path)
            self.assertEqual((status, location), (302, "/latest/"), path)
            self.assertNotIn("secret", body)

    def test_unknown_version_is_not_found(self) -> None:
        self.assertEqual(self._request("/v9.9.9/")[0], 404)

    def test_unbuilt_version_starts_its_build_and_shows_progress(self) -> None:
        status, _, body = self._request("/v1.0.0/page.html")

        self.assertEqual(status, 202)
        self.assertIn('data-build="v1.0.0"', body)
        self.assertIn("<progress", body)
        self.assertTrue((self.library.queue / "v1.0.0").exists())

    def test_api_reports_every_version(self) -> None:
        status, _, body = self._request("/api/versions")

        self.assertEqual(status, 200)
        self.assertEqual(
            [(entry["name"], entry["built"]) for entry in json.loads(body)],
            [("latest", True), ("v1.0.0", False)],
        )

    def test_overview_and_its_script_are_served(self) -> None:
        status, _, body = self._request("/versions/")
        self.assertEqual(status, 200)
        self.assertIn("<tbody data-versions>", body)
        self.assertIn('src="/_docs/versions.js"', body)
        self.assertIn("docsVersions", self._request("/_docs/versions.js")[2])

    def test_head_sends_no_body(self) -> None:
        self.assertEqual(self._request("/latest/", "HEAD"), (200, None, ""))


if __name__ == "__main__":
    unittest.main()
