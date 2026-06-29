"""Lint guard: import-linter architectural contracts MUST hold.

Background
==========
CodeQL ``py/unsafe-cyclic-import`` repeatedly flagged the dev/CI deploy
package ``cli.administration.deploy.development`` (compose <-> common <->
deps). Static linters (ruff) do not model the module-import graph, so
they cannot catch a re-introduced cycle. import-linter does.

The contracts live in ``[tool.importlinter]`` in ``pyproject.toml``; this
test runs them so a cycle regression fails CI rather than only surfacing
later in a CodeQL scan. Run them directly with ``lint-imports``.

Skip behaviour
==============
import-linter is a dev dependency (``pip install .[dev]`` /
``make install-python-dev``). Where it is absent the test skips rather
than fails, so a minimal runtime-only environment is not blocked; CI
installs the dev extra and therefore enforces the contracts.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import unittest

from . import PROJECT_ROOT

_LINT_IMPORTS = shutil.which("lint-imports")


class TestImportContracts(unittest.TestCase):
    """The ``[tool.importlinter]`` contracts in ``pyproject.toml`` hold."""

    @unittest.skipUnless(
        _LINT_IMPORTS,
        "import-linter not installed; run `make install-python-dev`",
    )
    def test_import_linter_contracts_hold(self) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (str(PROJECT_ROOT), env.get("PYTHONPATH", "")) if p
        )
        result = subprocess.run(
            [_LINT_IMPORTS],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg="import-linter contracts broken:\n" + result.stdout + result.stderr,
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
