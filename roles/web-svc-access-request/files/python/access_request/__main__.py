from __future__ import annotations

import logging
import os
from wsgiref.simple_server import make_server

from .app import from_environment


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ["ACCESS_REQUEST_PORT"])
    with make_server("0.0.0.0", port, from_environment()) as server:  # noqa: S104 - the container network is the only listener scope
        server.serve_forever()


if __name__ == "__main__":
    main()
