from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def _value_generator_cls() -> type[object]:
    """
    Load ValueGenerator from utils/manager/value_generator.py.

    Assumptions:
    - utils/manager/__init__.py exists (package import works)
    - plugins/filter/ is located at repo root
    """
    # nocheck: project-root-import  ansible loads filter plugins outside the project package, so relative imports don't resolve
    repo_root = Path(__file__).resolve().parents[2]
    utils_path = repo_root / "utils"

    if not utils_path.is_dir():
        raise RuntimeError(f"utils directory not found at: {utils_path}")

    if str(utils_path) not in sys.path:
        sys.path.insert(0, str(utils_path))

    from manager.value_generator import ValueGenerator

    return ValueGenerator


def strong_password(length: int = 32) -> str:
    ValueGenerator = _value_generator_cls()
    return ValueGenerator().generate_strong_password(int(length))


class FilterModule:
    def filters(self):
        return {
            "strong_password": strong_password,
        }
