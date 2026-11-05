"""Loads the decider package svc-ai-s1 owns and its consumers stage.

The package ships under ``roles/svc-ai-s1/files/python`` so the role can copy
it into a consumer's build context, which puts it outside the import path the
test session runs with. Each module is loaded here by path once, so the tests
below address the same objects the staged copy provides.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[7]
PACKAGE_DIR: Path = PROJECT_ROOT / "roles/svc-ai-s1/files/python/infinito_decider"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"infinito_decider_{name}", PACKAGE_DIR / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HISTORY = _load("history")
JUDGE = _load("judge")
SAMPLING = _load("sampling")
