"""Compatibility wrapper.

The implementation lives in ``cli/build/docs/integration_matrix/__main__.py``;
this package re-exports its public API so ``from
cli.build.docs.integration_matrix import ...`` works.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[4]
