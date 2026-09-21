"""HTTP front of the documentation library.

Environment:
    DOCS_SOURCE_REPO: git URL of the documented repository.
    DOCS_DATA_DIR: volume holding the mirror and the site of every version.
    DOCS_BUILD_JOBS: parallel Sphinx processes per build.
    DOCS_FETCH_INTERVAL: seconds between two fetches of new commits and tags.
    DOCS_PORT: port to listen on.
"""

from __future__ import annotations

import html
import json
import os
import threading
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from infinito_docs.library import LATEST, Library

PACKAGE_DIR = Path(__file__).resolve().parent
SCRIPT = PACKAGE_DIR / "assets" / "js" / "versions.js"

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<script src="/_docs/versions.js" defer></script>
</head>
<body>
<main>
<h1>{title}</h1>
{body}
</main>
</body>
</html>
"""

OVERVIEW = """<table>
<thead><tr><th>Version</th><th>Status</th><th>Progress</th></tr></thead>
<tbody data-versions></tbody>
</table>
"""

BUILDING = """<section data-build="{version}">
<p>This version is not built yet. The build started and this page reloads once it is done.</p>
<p data-phase>queued</p>
<progress max="100" value="0" aria-label="Build progress of {version}"></progress>
<pre></pre>
</section>
<p><a href="/versions/">All versions</a></p>
"""


class DocsHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, library, **kwargs):
        self.library = library
        super().__init__(*args, **kwargs)

    def do_GET(self):
        self._route(head=False)

    def do_HEAD(self):
        self._route(head=True)

    def _send(self, status, content_type, body, head):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _redirect(self, location):
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _page(self, status, title, body, head):
        page = PAGE.format(title=html.escape(title), body=body)
        self._send(status, "text/html; charset=utf-8", page.encode("utf-8"), head)

    def _file(self, path, head):
        self._send(HTTPStatus.OK, self.guess_type(str(path)), path.read_bytes(), head)

    def _route(self, head):
        path = unquote(urlsplit(self.path).path)
        if path == "/":
            self._redirect(f"/{LATEST}/")
        elif path in {"/versions", "/versions/"}:
            self._page(HTTPStatus.OK, "Documentation versions", OVERVIEW, head)
        elif path == "/api/versions":
            body = json.dumps(self.library.status()).encode("utf-8")
            self._send(HTTPStatus.OK, "application/json", body, head)
        elif path == "/_docs/versions.js":
            self._file(SCRIPT, head)
        else:
            self._version(path, head)

    def _version(self, path, head):
        version, slash, rest = path.lstrip("/").partition("/")
        if version not in self.library.versions():
            self.send_error(HTTPStatus.NOT_FOUND)
        elif not slash:
            self._redirect(f"/{version}/")
        elif not self.library.servable(version):
            self.library.request(version)
            body = BUILDING.format(version=html.escape(version))
            self._page(HTTPStatus.ACCEPTED, f"Building {version}", body, head)
        elif (target := self.library.resolve(version, rest)) is None:
            self._redirect(f"/{version}/")
        elif target.name == "index.html" and rest and not rest.endswith(("/", ".html")):
            self._redirect(f"/{version}/{rest}/")
        else:
            self._file(target, head)


def main():
    library = Library(
        os.environ["DOCS_SOURCE_REPO"],
        os.environ["DOCS_DATA_DIR"],
        int(os.environ["DOCS_BUILD_JOBS"]),
        PACKAGE_DIR,
    )
    threading.Thread(
        target=library.run_builder,
        args=(int(os.environ["DOCS_FETCH_INTERVAL"]),),
        daemon=True,
    ).start()
    handler = partial(DocsHandler, library=library)
    ThreadingHTTPServer(("", int(os.environ["DOCS_PORT"])), handler).serve_forever()


if __name__ == "__main__":
    main()
