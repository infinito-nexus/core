from __future__ import annotations

import fnmatch
import functools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from utils.cache import PROJECT_ROOT
from utils.cache.files import iter_project_files, read_text

SPARSE = PROJECT_ROOT / "cli" / "contributing" / "role" / "skeleton" / "sparse.txt"
MANIFEST = json.dumps(
    {
        "name": "skeleton-sparse-probe",
        "description": "Probe application rendered inside a sparse checkout",
        "homepage": "https://example.org/",
        "license": "MIT",
        "image": "ghcr.io/example/probe:1.0.0",
        "port": 8080,
        "database": "postgres",
        "login": "oidc",
        "features": ["email", "redis"],
        "volumes": ["/data"],
    }
)
PROBE = """
import contextlib, io, sys
from cli.contributing.role.skeleton.__main__ import main
sys.stdin = io.StringIO(sys.argv[2])
with contextlib.redirect_stdout(io.StringIO()):
    code = main(["render", "--target", sys.argv[1]])
for module in list(sys.modules.values()):
    print(getattr(module, "__file__", None) or "")
sys.exit(code)
"""


@functools.cache
def _patterns() -> tuple[str, ...]:
    return tuple(
        line.strip() for line in read_text(str(SPARSE)).splitlines() if line.strip()
    )


def _listed(relative: str) -> bool:
    for pattern in _patterns():
        rooted = pattern.removeprefix("/")
        if rooted.endswith("/"):
            if relative.startswith(rooted):
                return True
            continue
        parts, wanted = relative.split("/"), rooted.split("/")
        if len(parts) == len(wanted) and all(
            fnmatch.fnmatchcase(part, want)
            for part, want in zip(parts, wanted, strict=True)
        ):
            return True
    return False


def _sparse_copy(root: Path) -> None:
    for source in iter_project_files():
        relative = Path(source).relative_to(PROJECT_ROOT).as_posix()
        if _listed(relative):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def _env() -> dict[str, str]:
    return {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}


class TestSparse(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._checkout = tempfile.TemporaryDirectory()
        cls.core = Path(cls._checkout.name).resolve() / "core"
        _sparse_copy(cls.core)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._checkout.cleanup()

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()

    def test_every_pattern_is_rooted(self):
        self.assertEqual(
            [], [pattern for pattern in _patterns() if not pattern.startswith("/")]
        )

    def test_every_module_a_render_loads_is_listed(self):
        loaded = subprocess.run(
            [sys.executable, "-c", PROBE, str(self.tmp), MANIFEST],
            cwd=PROJECT_ROOT,
            env=_env(),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        prefix = f"{PROJECT_ROOT}/"
        modules = {
            path.removeprefix(prefix) for path in loaded if path.startswith(prefix)
        }
        self.assertEqual([], sorted(path for path in modules if not _listed(path)))

    def test_a_render_inside_a_sparse_checkout_succeeds(self):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "cli.contributing.role.skeleton",
                "render",
                "--target",
                str(self.tmp / "out"),
            ],
            cwd=self.core,
            env=_env(),
            input=MANIFEST,
            capture_output=True,
            text=True,
            check=False,
        )
        role_dir = self.tmp / "out" / "web-app-cst-skeleton-sparse-probe"
        self.assertEqual(
            (0, f"{role_dir}\n", ""), (result.returncode, result.stdout, result.stderr)
        )

    def test_the_sparse_checkout_serves_the_renderer_itself(self):
        templates = subprocess.run(
            [
                sys.executable,
                "-c",
                "import cli.contributing.role.skeleton.render as r; print(r.TEMPLATE_DIR)",
            ],
            cwd=self.core,
            env=_env(),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertEqual(str(self.core / "templates" / "roles" / "skeleton"), templates)


if __name__ == "__main__":
    unittest.main()
