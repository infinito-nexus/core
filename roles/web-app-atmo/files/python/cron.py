from __future__ import annotations

import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from os import environ
from pathlib import Path

REQUIRED_ENV = (
    "ATMO_CRON_URL",
    "ATMO_CRON_SECRET",
    "ATMO_CRON_INTERVAL_SECONDS",
    "ATMO_CRON_TIMEOUT_SECONDS",
    "ATMO_CRON_BEAT_PATH",
)


@dataclass(frozen=True)
class Config:
    url: str
    secret: str
    interval_seconds: int
    timeout_seconds: int
    beat_path: Path


def _positive_int(env, key: str) -> int:
    try:
        value = int(env[key])
    except ValueError as exc:
        raise SystemExit(f"atmo-cron: {key} is not an integer") from exc
    if value < 1:
        raise SystemExit(f"atmo-cron: {key} must be at least 1")
    return value


def load_config(env) -> Config:
    """Read the ticker configuration and refuse to start on a gap.

    Args:
        env: mapping of environment variables, normally ``os.environ``.

    Returns:
        The parsed configuration.
    """
    missing = [key for key in REQUIRED_ENV if not str(env.get(key, "")).strip()]
    if missing:
        raise SystemExit(f"atmo-cron: missing environment: {', '.join(missing)}")
    if not env["ATMO_CRON_URL"].startswith(("https://", "http://")):
        raise SystemExit("atmo-cron: ATMO_CRON_URL is not an http(s) URL")
    return Config(
        url=env["ATMO_CRON_URL"],
        secret=env["ATMO_CRON_SECRET"],
        interval_seconds=_positive_int(env, "ATMO_CRON_INTERVAL_SECONDS"),
        timeout_seconds=_positive_int(env, "ATMO_CRON_TIMEOUT_SECONDS"),
        beat_path=Path(env["ATMO_CRON_BEAT_PATH"]),
    )


def tick(config: Config, opener=urllib.request.urlopen) -> int:
    """Run one ingestion cycle of the atmo worker.

    Args:
        config: the ticker configuration.
        opener: ``urllib.request.urlopen`` compatible callable.

    Returns:
        The HTTP status the worker answered with; any non-2xx status raises.
    """
    request = urllib.request.Request(  # noqa: S310 - load_config admits only http(s) URLs
        config.url,
        data=b"{}",
        headers={"Content-Type": "application/json", "X-Cron-Secret": config.secret},
        method="POST",
    )
    with opener(request, timeout=config.timeout_seconds) as response:
        return response.status


def beat(path: Path, now: float) -> None:
    path.write_text(f"{now}\n", encoding="utf-8")


def healthy(path: Path, now: float, interval_seconds: int) -> bool:
    try:
        last = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return now - last <= 3 * interval_seconds


def main(argv: list, env) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command not in ("run", "health"):
        print("atmo-cron: usage: cron.py run|health", file=sys.stderr)
        return 2
    config = load_config(env)
    if command == "health":
        return (
            0 if healthy(config.beat_path, time.time(), config.interval_seconds) else 1
        )
    while True:
        try:
            tick(config)
            beat(config.beat_path, time.time())
        except (OSError, urllib.error.URLError):
            traceback.print_exc()
        time.sleep(config.interval_seconds)


if __name__ == "__main__":
    sys.exit(main(sys.argv, environ))
