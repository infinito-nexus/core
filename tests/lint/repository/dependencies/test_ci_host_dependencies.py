"""Lint guard: the runner-host CLI imports against the base dependency set only.

`scripts/tests/deploy/ci/all.sh` bootstraps the GitHub Actions runner host with
`scripts/install/python.sh`, which installs the project without extras. The host
then runs `cli.administration.deploy.development` outside the project image, so
every module-level import that chain reaches must be satisfiable from
`[project.dependencies]` alone. A package that only `[project.optional-dependencies].deploy`
declares is present in the image, not on the host.

The check imports the CLI's command modules with every `deploy` package blocked,
which is what a host that installed the base set sees. Before this guard the gap
was invisible: the `ubuntu-latest` image happened to preinstall the missing
packages, so a new import surfaced only when GitHub rebased the image or the
import reached a package the image never shipped.

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

from utils.cache.files import read_text

from . import PROJECT_ROOT

_PYPROJECT = PROJECT_ROOT / "pyproject.toml"

_DEFAULT_ENV = PROJECT_ROOT / "default.env"

_SRC_DIR_RE = re.compile(r"^INFINITO_SRC_DIR=(.+)$", re.MULTILINE)

_DEPLOY_EXTRA = "deploy"

_PROBE = """
import sys

blocked = set(sys.argv[1].split(","))


class ImageOnlyBlocker:
    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split(".")[0]
        if top in blocked:
            raise ImportError(
                f"{top!r} is a [project.optional-dependencies].deploy package "
                "and is not installed on the runner host"
            )
        return None


sys.meta_path.insert(0, ImageOnlyBlocker())

from cli.administration.deploy.development.cli import _build_parser

_build_parser("cli.administration.deploy.development")
"""


def _top_level_name(requirement: str) -> str:
    """Return the import name a requirement string installs.

    Args:
        requirement: a PEP 508 requirement as written in `pyproject.toml`,
            optionally carrying a direct-URL (`name @ https://...`) or a
            version specifier.
    """
    name = re.split(r"[\s@<>=!~\[;]", requirement.strip(), maxsplit=1)[0]
    return name.replace("-", "_")


def _deploy_top_level_names() -> list[str]:
    data = tomllib.loads(read_text(str(_PYPROJECT)))
    extras = data["project"]["optional-dependencies"]
    if _DEPLOY_EXTRA not in extras:
        raise AssertionError(
            f"pyproject.toml declares no '{_DEPLOY_EXTRA}' extra; the runner host "
            "bootstrap has no way to tell base from image-only dependencies"
        )
    return sorted({_top_level_name(item) for item in extras[_DEPLOY_EXTRA]})


def _src_dir() -> str:
    match = _SRC_DIR_RE.search(read_text(str(_DEFAULT_ENV)))
    if match is None:
        raise AssertionError(f"INFINITO_SRC_DIR is not declared in {_DEFAULT_ENV}")
    return match.group(1).strip()


class TestCiHostDependencies(unittest.TestCase):
    """The runner-host CLI builds its parser without any `deploy` package."""

    def test_cli_parser_builds_without_deploy_extra(self) -> None:
        blocked = _deploy_top_level_names()

        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            path for path in (str(PROJECT_ROOT), env.get("PYTHONPATH", "")) if path
        )
        env["INFINITO_SRC_DIR"] = _src_dir()

        result = subprocess.run(
            [sys.executable, "-c", _PROBE, ",".join(blocked)],
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
                "cli.administration.deploy.development imports a package that the "
                "runner host does not install. Either move it into "
                "[project.dependencies] (it is then paid for on every CI job) or "
                "make the import lazy:\n" + result.stderr
            ),
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
