"""Pin the vulnerability scan of a development or CI deploy to one engine."""

from __future__ import annotations

import os
import random
from pathlib import Path
from typing import TYPE_CHECKING

from utils.security.database import fetch_url, refresh
from utils.security.engine import (
    ENGINE_ENV,
    databases_for,
    deploy_overrides,
    draw_engine,
    pinned_engine,
)
from utils.security.pipeline import pipeline

if TYPE_CHECKING:
    from collections.abc import Callable

HOST_PATH_ENV = "INFINITO_VULNERABILITY_DB_HOST_PATH"
TARGET_DIR_ENV = "INFINITO_VULNERABILITY_DB_DIR"


def provided_databases(root: Path, engine: str) -> None:
    """Fail unless every database a pinned *engine* reads is in *root*.

    Raises:
        SystemExit: a database was not provided.
    """
    for name in databases_for(engine):
        path = root / name
        if not path.is_dir() or not any(path.iterdir()):
            raise SystemExit(
                f"{ENGINE_ENV}={engine} but no {name} database at {path}; "
                "provide it before the deploy"
            )


def inventory_overrides(
    rng: random.Random,
    refresher: Callable[[Path, list[str]], list[str]],
) -> dict:
    """Return the inventory override of one development or CI deploy.

    A pinned engine reads databases that were provided and never downloads
    one. Without a pin the deploy draws an engine and refreshes the shared
    host databases it reads first.

    Args:
        rng: draws the engine of an unpinned deploy.
        refresher: ``(root, engines) -> error lines``, see
            :func:`utils.security.database.refresh`.

    Raises:
        SystemExit: a provided database is missing or a refresh failed.
    """
    root = Path(os.environ[HOST_PATH_ENV])
    engine = pinned_engine()
    if engine:
        provided_databases(root, engine)
    else:
        engine = draw_engine(rng)
        print(f">>> vulnerability engine of this deploy: {engine}")
        errors = refresher(root, databases_for(engine))
        if errors:
            raise SystemExit("\n".join(errors))
    return deploy_overrides(engine, os.environ[TARGET_DIR_ENV])


def refresh_shared(root: Path, engines: list[str]) -> list[str]:
    """:func:`utils.security.database.refresh` with the real engines and downloads."""
    return refresh(root, engines, pipeline().default_runner, fetch_url)


def deploy_inventory_overrides() -> dict:
    """:func:`inventory_overrides` for a real deploy."""
    return inventory_overrides(random.SystemRandom(), refresh_shared)
