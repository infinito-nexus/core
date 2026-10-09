"""No top-level file under the configured `module_utils` path shadows Ansible's own.

`ansible.cfg` points `module_utils` at `./utils`, so every top-level `.py` there
becomes importable as `ansible.module_utils.<stem>` and is bundled into the
payload zip Ansible ships for each task. A stem that Ansible already uses wins
over the real module inside that zip, and every module importing from it dies at
run time, far from the file that caused it.

A `utils/errors.py` did exactly that: `ansible.module_utils.errors` is where
Ansible keeps `AliasError`, so `uri` and `get_url` failed with an ImportError
pointing into a temporary zip rather than at the repository.

Fix a hit by moving the file into a subpackage (`utils/<topic>/<name>.py`).
Nested modules land under `ansible.module_utils.<topic>.<name>` and cannot
collide.
"""

from __future__ import annotations

import configparser
import importlib.util
import unittest
from typing import TYPE_CHECKING

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_ANSIBLE_CFG = PROJECT_ROOT / "ansible.cfg"


def _module_utils_dir() -> Path:
    """The directory `ansible.cfg` exposes as `ansible.module_utils`."""
    parser = configparser.ConfigParser()
    parser.read(_ANSIBLE_CFG)
    configured = parser.get("defaults", "module_utils", fallback="").strip()
    if not configured:
        raise unittest.SkipTest(
            f"{_ANSIBLE_CFG} sets no 'module_utils' path, so nothing can shadow."
        )
    return (PROJECT_ROOT / configured).resolve()


def _shadows_ansible(stem: str) -> bool:
    try:
        return importlib.util.find_spec(f"ansible.module_utils.{stem}") is not None
    except (ImportError, AttributeError, ValueError):
        return False


class TestNoModuleUtilsShadowing(unittest.TestCase):
    def test_no_top_level_helper_shadows_an_ansible_module_util(self) -> None:
        module_utils_dir = _module_utils_dir()
        offenders = sorted(
            path.name
            for path in module_utils_dir.glob("*.py")
            if path.stem != "__init__" and _shadows_ansible(path.stem)
        )
        self.assertEqual(
            offenders,
            [],
            f"These files in {module_utils_dir.relative_to(PROJECT_ROOT)} are "
            f"exposed as 'ansible.module_utils.<stem>' and shadow a module "
            f"Ansible ships under that exact name. Every task whose module "
            f"imports the real one then fails inside the payload zip. Move each "
            f"into a subpackage instead. Found {offenders}.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
