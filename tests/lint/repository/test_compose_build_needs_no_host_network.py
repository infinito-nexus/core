"""Compose hands a build to ``docker buildx bake`` and grants it only the
``fs.read`` entitlement of the build context. Since Buildx 0.38.0 a block with
``network: host`` stops there with ``additional privileges requested``, and
declaring ``build.entitlements`` or setting ``COMPOSE_BAKE=false`` does not
change that, so such a service cannot be built through ``make compose-up``.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from utils.cache.files import iter_project_files
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

STACK_FILE = str(PROJECT_ROOT / "compose.yml")
OVERRIDES = f"{PROJECT_ROOT / 'compose'}/"
STACK_BUILD = "compose.yml: infinito"


def _builds(path):
    """Yield ``(label, build)`` for every service of a compose file that builds.

    Args:
        path: compose file to read; a YAML file without ``services`` yields nothing.
    """
    document = load_yaml_any(path)
    if not isinstance(document, dict):
        return
    for name, service in (document.get("services") or {}).items():
        build = service.get("build")
        if isinstance(build, dict):
            yield f"{Path(path).relative_to(PROJECT_ROOT)}: {name}", build


class TestComposeBuildNeedsNoHostNetwork(unittest.TestCase):
    def test_no_build_block_asks_for_host_networking(self) -> None:
        compose_files = [
            path
            for path in sorted(iter_project_files(extensions=(".yml",)))
            if path == STACK_FILE or path.startswith(OVERRIDES)
        ]
        builds = dict(hit for path in compose_files for hit in _builds(path))
        self.assertIn(STACK_BUILD, builds, "the stack build block was not scanned")
        offenders = [
            label for label, build in builds.items() if build.get("network") == "host"
        ]
        self.assertEqual(
            [],
            offenders,
            "Compose cannot grant bake the network.host entitlement "
            "(Buildx >= 0.38.0 refuses the build); drop 'network: host' from: "
            f"{offenders}",
        )


if __name__ == "__main__":
    unittest.main()
