from __future__ import annotations

import sys
import time
import traceback
import urllib.error
from os import environ

from atmo_bridge.clients import BridgeError, Mobilizon, Pds
from atmo_bridge.config import load_config
from atmo_bridge.cycle import healthy, run_cycle
from atmo_bridge.store import Store


def _log(message: str) -> None:
    print(f"atmo-bridge: {message}", file=sys.stderr, flush=True)


def main(argv: list, env) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command not in ("run", "health"):
        _log("usage: bridge.py run|health")
        return 2
    config = load_config(env)
    store = Store(config.state_path)
    if command == "health":
        return 0 if healthy(store, time.time(), config.interval_seconds) else 1
    pds = Pds(config.pds_url)

    def sink_factory() -> Mobilizon:
        return Mobilizon(
            config.mobilizon_url, config.mobilizon_email, config.mobilizon_password
        ).login()

    while True:
        try:
            applied = run_cycle(
                store, pds, sink_factory, config.appview_url, time.time(), _log
            )
            if applied:
                _log(f"applied {applied} change(s)")
        except (BridgeError, OSError, KeyError, ValueError, urllib.error.URLError):
            traceback.print_exc()
        time.sleep(config.interval_seconds)


if __name__ == "__main__":
    sys.exit(main(sys.argv, environ))
