# nocheck: mirrored-unit-test - the process entrypoint starts uvicorn inside the API image; the Playwright spec of web-svc-api exercises it end to end
from __future__ import annotations

import os
import threading
from pathlib import Path

import uvicorn

from infinito_api.app import create_app
from infinito_api.repository import Repository


def main() -> None:
    repository = Repository(
        Path(os.environ["API_DATA_DIR"]) / "repo.git",
        os.environ["API_SOURCE_REPOSITORY"],
        os.environ["API_FORKS"],
        Path(os.environ["API_SNAPSHOT_DIR"]),
    )
    repository.initialize()
    threading.Thread(
        target=repository.run_fetcher,
        args=(int(os.environ["API_FETCH_INTERVAL"]),),
        daemon=True,
    ).start()
    uvicorn.run(
        create_app(repository),
        host="0.0.0.0",  # noqa: S104 - the container network is the only interface and the proxy fronts it
        port=int(os.environ["API_PORT"]),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
