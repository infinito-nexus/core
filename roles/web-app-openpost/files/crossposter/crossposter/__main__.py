from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import config as settings
from . import web
from .openpost import OpenPost, TargetError

LIST_COLUMNS = (
    "id",
    "state",
    "route",
    "network",
    "target",
    "attempts",
    "source_url",
    "publication_id",
    "last_error",
)
HEALTHY = ("active", "standby", "waiting")
STALE_INTERVALS = 3
LOG = logging.getLogger("crossposter")


def _client(loaded: settings.Config) -> OpenPost:
    return OpenPost(
        loaded.openpost.base_url,
        loaded.openpost.host,
        loaded.openpost.token,
        loaded.openpost.workspace,
    )


def validate(path: str) -> settings.Config:
    loaded = settings.load(path)
    client = _client(loaded)
    for route in loaded.routes:
        try:
            client.destinations(route.targets)
        except TargetError as error:
            raise settings.ConfigError(
                f"route '{route.name}': targets: {error}"
            ) from error
    return loaded


def command_validate(path: str) -> int:
    try:
        loaded = validate(path)
    except settings.ConfigError as error:
        print(f"invalid crossposter configuration: {error}", file=sys.stderr)
        return 2
    except web.RequestError as error:
        print(
            f"OpenPost could not be asked about the targets: {error}", file=sys.stderr
        )
        return 3
    print(f"{len(loaded.routes)} route(s) valid")
    return 0


def liveness(path: str) -> tuple[Path, float]:
    raw = json.loads(Path(path).read_text())
    return Path(raw["heartbeat_file"]), float(raw["poll_interval_seconds"])


def wait_for_configuration(path: str, error: Exception) -> float:
    heartbeat, interval = liveness(path)
    heartbeat.write_text(f"{time.time():.0f} waiting\n")
    LOG.warning("crossposter waits for a valid configuration: %s", error)
    return interval


def command_run(path: str) -> int:
    from .service import Service
    from .store import Store

    while True:
        try:
            loaded = validate(path)
            break
        except (settings.ConfigError, web.RequestError) as error:
            time.sleep(wait_for_configuration(path, error))
    Service(loaded, Store(loaded.dsn), _client(loaded)).run_forever()
    return 0


def command_list(path: str) -> int:
    from .store import Store

    loaded = settings.load(path)
    rows = Store(loaded.dsn).everything()
    print("\t".join(LIST_COLUMNS))
    for row in rows:
        print(
            "\t".join(
                str(row[column]).replace("\n", " ")[:120] for column in LIST_COLUMNS
            )
        )
    return 0


def command_health(path: str) -> int:
    heartbeat, interval = liveness(path)
    if not heartbeat.is_file():
        return 1
    stamp, _, state = heartbeat.read_text().strip().partition(" ")
    fresh = time.time() - float(stamp) < STALE_INTERVALS * interval
    return 0 if fresh and state in HEALTHY else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="crossposter")
    parser.add_argument("command", choices=("run", "validate", "list", "health"))
    parser.add_argument("--config", required=True)
    arguments = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    commands = {
        "run": command_run,
        "validate": command_validate,
        "list": command_list,
        "health": command_health,
    }
    return commands[arguments.command](arguments.config)


if __name__ == "__main__":
    sys.exit(main())
