from __future__ import annotations

from dataclasses import dataclass

REQUIRED_ENV = (
    "BRIDGE_PDS_URL",
    "BRIDGE_APPVIEW_URL",
    "BRIDGE_MOBILIZON_URL",
    "BRIDGE_MOBILIZON_EMAIL",
    "BRIDGE_MOBILIZON_PASSWORD",
    "BRIDGE_STATE_PATH",
    "BRIDGE_INTERVAL_SECONDS",
)
URL_SCHEMES = ("https://", "http://")


@dataclass(frozen=True)
class Config:
    pds_url: str
    appview_url: str
    mobilizon_url: str
    mobilizon_email: str
    mobilizon_password: str
    state_path: str
    interval_seconds: int


def load_config(env) -> Config:
    """Read the bridge configuration and refuse to start on a gap.

    Args:
        env: mapping of environment variables, normally ``os.environ``.

    Returns:
        The parsed configuration.
    """
    missing = [key for key in REQUIRED_ENV if not str(env.get(key, "")).strip()]
    if missing:
        raise SystemExit(f"atmo-bridge: missing environment: {', '.join(missing)}")
    try:
        interval = int(env["BRIDGE_INTERVAL_SECONDS"])
    except ValueError as exc:
        raise SystemExit(
            "atmo-bridge: BRIDGE_INTERVAL_SECONDS is not an integer"
        ) from exc
    if interval < 1:
        raise SystemExit("atmo-bridge: BRIDGE_INTERVAL_SECONDS must be at least 1")
    for key in ("BRIDGE_PDS_URL", "BRIDGE_APPVIEW_URL", "BRIDGE_MOBILIZON_URL"):
        if not env[key].startswith(URL_SCHEMES):
            raise SystemExit(f"atmo-bridge: {key} is not an http(s) URL")
    return Config(
        pds_url=env["BRIDGE_PDS_URL"].rstrip("/"),
        appview_url=env["BRIDGE_APPVIEW_URL"].rstrip("/"),
        mobilizon_url=env["BRIDGE_MOBILIZON_URL"].rstrip("/"),
        mobilizon_email=env["BRIDGE_MOBILIZON_EMAIL"],
        mobilizon_password=env["BRIDGE_MOBILIZON_PASSWORD"],
        state_path=env["BRIDGE_STATE_PATH"],
        interval_seconds=interval,
    )
