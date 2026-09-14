"""Lint guard: the deploy toolchain names an exact ansible version.

`make install-python` runs `scripts/install/python.sh deploy`, so the `deploy`
extra is what every deploy host actually installs. Declared as a bare `ansible`,
that extra walked across ansible-core major versions between two deploys of the
same commit, and the jump is what carried in the dead hardware-fact collector
this repository now routes around in `plugins/lookup/resource.py`.

The pin does not fix that upstream bug: the pinned release still reads
`/sys/block/<dev>/size` without a None guard. It fixes the part this repository
owns, which is that the toolchain no longer changes under the operator
unannounced.
"""

from __future__ import annotations

import tomllib
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

_PACKAGE = "ansible"
_EXTRA = "deploy"
_PYPROJECT = PROJECT_ROOT / "pyproject.toml"


def _deploy_requirements() -> list[str]:
    data = tomllib.loads(read_text(str(_PYPROJECT)))
    return data.get("project", {}).get("optional-dependencies", {}).get(_EXTRA, [])


class TestDeployToolchainPin(unittest.TestCase):
    def test_ansible_is_declared_in_the_deploy_extra(self) -> None:
        declared = [
            requirement
            for requirement in _deploy_requirements()
            if requirement.split("==")[0].split("[")[0].strip() == _PACKAGE
        ]
        self.assertEqual(
            len(declared),
            1,
            f"[project.optional-dependencies].{_EXTRA} in {_PYPROJECT} must declare "
            f"'{_PACKAGE}' exactly once; found {declared}.",
        )

    def test_ansible_is_pinned_to_one_exact_version(self) -> None:
        requirement = next(
            requirement
            for requirement in _deploy_requirements()
            if requirement.split("==")[0].split("[")[0].strip() == _PACKAGE
        )
        self.assertIn(
            "==",
            requirement,
            f"'{requirement}' in the {_EXTRA} extra of {_PYPROJECT} carries no "
            f"'=='. An unpinned ansible lets the deploy toolchain cross a major "
            f"version between two deploys of the same commit, which is how the "
            f"hardware-fact collector regression reached this repository. Pin it "
            f"to a version you verified with 'pip install ansible==<X>' plus "
            f"'ansible --version'.",
        )
        version = requirement.split("==", 1)[1].strip()
        self.assertNotIn(
            "*",
            version,
            f"'{requirement}' pins a range, not a version. A wildcard still lets "
            f"ansible-core move inside the line.",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
