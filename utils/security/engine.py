"""Which vulnerability engines a development or CI deploy runs.

Every such deploy runs Syft and one drawn engine, plus Grype over the
source-built runtimes. A CI deploy job pins the engine its matrix row drew in
``INFINITO_VULNERABILITY_ENGINE`` and provides the databases; a local deploy
draws one at random. Only production hosts run every engine of
``sys-ctl-hlth-runtime``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import random

ROLE = "sys-ctl-hlth-runtime"
SCANNERS = ("trivy", "grype", "osv")
SBOM_BUILDER = "syft"
RUNTIME_ENGINE = "grype"
ENGINE_ENV = "INFINITO_VULNERABILITY_ENGINE"


def pinned_engine() -> str:
    """Return the engine the environment pins, ``""`` when none is pinned."""
    return os.environ.get(ENGINE_ENV, "").strip()


def draw_engine(rng: random.Random) -> str:
    """Draw the engine of a local deploy."""
    return rng.choice(SCANNERS)


def _known(engine: str) -> str:
    if engine not in SCANNERS:
        raise ValueError(
            f"unknown vulnerability engine {engine!r}; expected {', '.join(SCANNERS)}"
        )
    return engine


def engines_for(engine: str) -> list[str]:
    """Return the engine list that runs *engine* behind a Syft SBOM.

    Raises:
        ValueError: *engine* is not one of :data:`SCANNERS`.
    """
    return [SBOM_BUILDER, _known(engine)]


def databases_for(engine: str) -> list[str]:
    """Return the databases a deploy pinned to *engine* reads.

    Grype also scans the source-built runtimes of every SBOM, so its
    database is always among them.

    Raises:
        ValueError: *engine* is not one of :data:`SCANNERS`.
    """
    return [name for name in SCANNERS if name in {_known(engine), RUNTIME_ENGINE}]


def deploy_overrides(engine: str, database_dir: str) -> dict:
    """Return the ``applications`` override that pins the scan to *engine*.

    Args:
        engine: the engine of the deploy.
        database_dir: where the deploy target reads the databases.

    Returns:
        The override of ``sys-ctl-hlth-runtime``'s ``runtime`` service.
    """
    return {
        ROLE: {
            "services": {
                "runtime": {
                    "engines": engines_for(engine),
                    "database_dir": database_dir,
                    "db_update": False,
                }
            }
        }
    }
