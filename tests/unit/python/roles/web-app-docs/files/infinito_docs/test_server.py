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
from .test_library import LibraryFixture

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
        cls.library = library.Library("unused", data, 1, data, data / "no-snapshot")
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

    def test_a_translated_language_starts_its_build_and_an_untranslated_one_is_not_found(
        self,
    ) -> None:
        index = self.library.translations / "latest" / "languages.json"
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(
            json.dumps(
                {"known": {"de": "Deutsch", "aa": "Afar"}, "translated": ["de"]}
            ),
            encoding="utf-8",
        )
        try:
            status, _, body = self._request("/latest/de/")
            self.assertEqual(status, 202)
            self.assertIn("latest/de", body)
            self.assertTrue((self.library.queue / "latest:de").exists())
            self.assertEqual(self._request("/latest/aa/")[0], 404)
            self.assertFalse((self.library.queue / "latest:aa").exists())
        finally:
            (self.library.queue / "latest:de").unlink(missing_ok=True)
            index.unlink(missing_ok=True)

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


CATALOG = """\
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"

%smsgid "Hello"
msgstr "%s"
"""

CATALOGS = {
    "de": CATALOG % ("", "Hallo"),
    "fr": CATALOG % ("", ""),
    "it": CATALOG % ("#, fuzzy\n", "Ciao"),
    "aa": None,
}


class TestDeployedLanguages(LibraryFixture):
    def setUp(self) -> None:
        super().setUp()
        snapshot = self.data / "snapshot"
        (snapshot / "meta").mkdir(parents=True)
        (snapshot / "VERSION").write_text("working tree", encoding="utf-8")
        (snapshot / "meta" / "languages.yml").write_text(
            "".join(f"{code}:\n  native: {code}\n" for code in CATALOGS),
            encoding="utf-8",
        )
        for code, body in CATALOGS.items():
            if body is None:
                continue
            catalog = snapshot / "locale" / code / "LC_MESSAGES" / "docs.po"
            catalog.parent.mkdir(parents=True)
            catalog.write_text(body, encoding="utf-8")
        self.shelf = library.Library(
            str(self.repo), self.data, 1, self.package, snapshot
        )
        self.httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(server.DocsHandler, library=self.shelf)
        )
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)

    def _statuses(self, segments):
        statuses = {}
        for segment in segments:
            connection = HTTPConnection(
                "127.0.0.1", self.httpd.server_address[1], timeout=5
            )
            connection.request("GET", f"/deployed/{segment}/")
            response = connection.getresponse()
            response.read()
            connection.close()
            statuses[segment] = response.status
        return statuses

    def test_the_snapshot_answers_every_language_as_its_build_will(self) -> None:
        segments = [*CATALOGS, "xx", "docs"]

        before = self._statuses(segments)
        self.shelf.build("deployed")
        self.assertTrue(self.shelf.servable("deployed"))
        self.assertFalse(self.shelf.outdated("deployed"))
        after = self._statuses(segments)

        self.assertEqual(
            before,
            {"de": 202, "fr": 404, "it": 404, "aa": 404, "xx": 202, "docs": 202},
        )
        self.assertEqual(
            {code for code, status in before.items() if status == 404},
            {code for code, status in after.items() if status == 404},
        )
        self.assertEqual(after["de"], 202)
        self.assertTrue((self.shelf.queue / "deployed:de").exists())
        self.assertFalse((self.shelf.queue / "deployed:fr").exists())

    def test_a_translated_site_already_on_disk_is_never_answered_404(self) -> None:
        stale = self.shelf.translations / "deployed" / "fr" / "html" / "index.html"
        stale.parent.mkdir(parents=True)
        stale.write_text("fr", encoding="utf-8")

        self.assertEqual(self._statuses(["fr"]), {"fr": 202})
        self.shelf.build("deployed")
        self.assertEqual(self._statuses(["fr"]), {"fr": 200})


if __name__ == "__main__":
    unittest.main()
