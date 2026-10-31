from __future__ import annotations

import argparse
import json
import logging
import ssl
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from provider.linkedin import Client, LinkedIn, Request
from provider.store import Store

LOG = logging.getLogger("provider")
HEALTH_TIMEOUT_SECONDS = 5


def load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def application(config: dict) -> LinkedIn:
    clients = {
        client_id: Client(
            secret=str(client["secret"]),
            name=str(client["name"]),
            redirect_uris=tuple(str(uri) for uri in client["redirect_uris"]),
        )
        for client_id, client in config["linkedin"]["clients"].items()
    }
    return LinkedIn(Store(), clients)


def handler_for(app: LinkedIn) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _dispatch(self) -> None:
            url = urllib.parse.urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            request = Request(
                method=self.command,
                path=url.path,
                query=dict(urllib.parse.parse_qsl(url.query, keep_blank_values=True)),
                headers={key.lower(): value for key, value in self.headers.items()},
                body=self.rfile.read(length) if length else b"",
            )
            response = app.handle(request)
            self.send_response(response.status)
            for name, value in response.headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(response.body)))
            self.end_headers()
            self.wfile.write(response.body)

        def do_GET(self) -> None:
            self._dispatch()

        def do_POST(self) -> None:
            self._dispatch()

        def do_PUT(self) -> None:
            self._dispatch()

        def do_DELETE(self) -> None:
            self._dispatch()

        def log_message(self, message: str, *args: object) -> None:
            LOG.info("%s %s", self.address_string(), message % args)

    return Handler


def serve(config: dict) -> int:
    handler = handler_for(application(config))
    plain = ThreadingHTTPServer(("0.0.0.0", int(config["http_port"])), handler)  # noqa: S104 published only on the role network and the CI loopback
    secure = ThreadingHTTPServer(("0.0.0.0", int(config["https_port"])), handler)  # noqa: S104 published only on the role network and the CI loopback
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(config["certificate"], config["key"])
    secure.socket = context.wrap_socket(secure.socket, server_side=True)
    threading.Thread(target=secure.serve_forever, daemon=True).start()
    LOG.info("serving LinkedIn on %s and %s", config["http_port"], config["https_port"])
    plain.serve_forever()
    return 0


def health(config: dict) -> int:
    url = f"http://127.0.0.1:{int(config['http_port'])}/__fake/health"
    try:
        with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT_SECONDS) as answer:
            return 0 if answer.status == 200 else 1
    except (urllib.error.URLError, OSError):
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="provider")
    parser.add_argument("command", choices=("serve", "health"))
    parser.add_argument("--config", required=True)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    config = load(args.config)
    return serve(config) if args.command == "serve" else health(config)


if __name__ == "__main__":
    sys.exit(main())
