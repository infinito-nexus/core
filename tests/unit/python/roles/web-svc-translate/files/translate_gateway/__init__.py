"""Loads the gateway's routing core, which ships under the role's files/."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[7]
PACKAGE_DIR: Path = (
    PROJECT_ROOT / "roles/web-svc-translate/files/python/translate_gateway"
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"translate_gateway.{name}", PACKAGE_DIR / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ERRORS = _load("errors")
SIGNATURE = _load("signature")

sys.modules.setdefault("translate_gateway", sys.modules[__name__])
sys.modules["translate_gateway.errors"] = ERRORS
sys.modules["translate_gateway.signature"] = SIGNATURE

CACHE = _load("cache")
ENGINES = _load("engines")
FAILURES = _load("failures")
MEMORY = _load("memory")
ROUTER = _load("router")
GATEWAY = _load("gateway")
