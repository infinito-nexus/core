"""Lint guard: the runner-host CLIs import against the base dependency set only.

`scripts/install/python.sh` installs the project without extras on every
GitHub Actions runner host that works outside the project image:
`scripts/tests/deploy/ci/all.sh` before `cli.administration.deploy.development`,
and every `scripts/github/update/*.sh` job before `make dotenv` (which runs
`cli.meta.env` and `cli.meta.cache`) and the update CLI the script names. Every
module-level import those entry points reach must be satisfiable from
`[project.dependencies]` and what those packages pull in themselves.

The probe blocks every installed import name whose distribution lies outside
that closure, which is what a host that installed the base set sees. Blocking
only the names the `deploy` extra lists missed what it brings in transitively:
`jinja2` arrived with ansible, so `make dotenv` broke on every update job once
`utils/cache/render.py` imported it.

Optionally-imported packages stay invisible here on purpose: `utils.cache.base`
wraps its ansible import in `try/except`, so blocking ansible changes nothing and
ansible correctly never has to reach the host.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
import unittest
from importlib import metadata

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from utils.cache.files import read_text

from . import PROJECT_ROOT

_PYPROJECT = PROJECT_ROOT / "pyproject.toml"

_DEFAULT_ENV = PROJECT_ROOT / "default.env"

_SRC_DIR_RE = re.compile(r"^INFINITO_SRC_DIR=(.+)$", re.MULTILINE)

_UPDATE_SCRIPT_RE = re.compile(r"^python3 -m (cli\.[\w.]+)", re.MULTILINE)

_DOTENV_MODULES = ("cli.meta.env.__main__", "cli.meta.cache.__main__")

_PROBE = """
import importlib
import sys

blocked = set(sys.argv[1].split(","))


class HostBlocker:
    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split(".")[0]
        if top in blocked:
            raise ImportError(
                f"{top!r} is not installed on the runner host: no package of "
                "[project.dependencies] pulls it in"
            )
        return None


sys.meta_path.insert(0, HostBlocker())

from cli.administration.deploy.development.cli import _build_parser

_build_parser("cli.administration.deploy.development")

for module in sys.argv[2].split(","):
    importlib.import_module(module)
"""


def _project() -> dict:
    return tomllib.loads(read_text(str(_PYPROJECT)))["project"]


def _base_closure() -> set[str]:
    pending = [Requirement(item) for item in _project()["dependencies"]]
    seen: set[str] = set()
    while pending:
        requirement = pending.pop()
        name = canonicalize_name(requirement.name)
        if name in seen:
            continue
        seen.add(name)
        try:
            requires = metadata.requires(name) or []
        except metadata.PackageNotFoundError:
            continue
        extras = {"", *requirement.extras}
        for line in requires:
            child = Requirement(line)
            if child.marker is None or any(
                child.marker.evaluate({"extra": extra}) for extra in extras
            ):
                pending.append(child)
    return seen


def _blocked_import_names() -> list[str]:
    allowed = _base_closure() | {canonicalize_name(_project()["name"])}
    return sorted(
        name
        for name, distributions in metadata.packages_distributions().items()
        if not (PROJECT_ROOT / name).exists()
        and not any(canonicalize_name(dist) in allowed for dist in distributions)
    )


def _host_modules() -> list[str]:
    scripts = sorted((PROJECT_ROOT / "scripts" / "github" / "update").glob("*.sh"))
    updates = {
        module
        for script in scripts
        for module in _UPDATE_SCRIPT_RE.findall(read_text(str(script)))
    }
    return [*_DOTENV_MODULES, *sorted(updates)]


def _src_dir() -> str:
    match = _SRC_DIR_RE.search(read_text(str(_DEFAULT_ENV)))
    if match is None:
        raise AssertionError(f"INFINITO_SRC_DIR is not declared in {_DEFAULT_ENV}")
    return match.group(1).strip()


class TestCiHostDependencies(unittest.TestCase):
    """The runner-host CLIs import with only the base install's packages."""

    def test_host_entry_points_import_without_extras(self) -> None:
        blocked = _blocked_import_names()
        self.assertIn("ansible", blocked)
        modules = _host_modules()
        self.assertIn("cli.contributing.update.docker", modules)

        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            path for path in (str(PROJECT_ROOT), env.get("PYTHONPATH", "")) if path
        )
        env["INFINITO_SRC_DIR"] = _src_dir()

        result = subprocess.run(
            [sys.executable, "-c", _PROBE, ",".join(blocked), ",".join(modules)],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            result.returncode,
            0,
            msg=(
                "A runner-host entry point imports a package that a base install "
                "does not provide. Either move it into [project.dependencies] (it "
                "is then paid for on every CI job) or make the import lazy:\n"
                + result.stderr
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
