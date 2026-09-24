"""Unit tests for utils.roles.deploy.role_deploy_modes.

Covers:
  * a declared mode set wins over the role's container shape;
  * an injector without a stack can still be offered compose and swarm;
  * a role that declares nothing falls back on its shape;
  * the ``enabled`` value of each offered mode is carried through.
"""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.roles.deploy import role_deploy_modes
from utils.roles.mapping import ROLE_FILE_META_SERVICES


class _RoleFixture:
    def __init__(self, root: Path):
        self.root = root

    def write(self, role_name: str, body: str, *, stack: bool) -> Path:
        role_dir = self.root / role_name
        (role_dir / "meta").mkdir(parents=True, exist_ok=True)
        (role_dir / ROLE_FILE_META_SERVICES).write_text(
            textwrap.dedent(body).lstrip("\n"), encoding="utf-8"
        )
        if stack:
            (role_dir / "templates").mkdir(parents=True, exist_ok=True)
            (role_dir / "templates" / "docker-compose.yml.j2").write_text(
                "services: {}\n", encoding="utf-8"
            )
        return role_dir


class TestRoleDeployModes(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.fx = _RoleFixture(Path(self._tmp.name))

    def test_declaration_outranks_a_missing_stack(self) -> None:
        role = self.fx.write(
            "web-svc-probe",
            """
            probe:
              modes:
                compose:
                  enabled: true
                swarm:
                  enabled: true
                host:
                  enabled: false
            """,
            stack=False,
        )
        self.assertEqual(
            role_deploy_modes(role, "web-svc-probe"),
            {"compose": True, "swarm": True, "host": False},
        )

    def test_declaration_outranks_a_present_stack(self) -> None:
        role = self.fx.write(
            "web-svc-probe",
            """
            probe:
              modes:
                host:
                  enabled: true
            """,
            stack=True,
        )
        self.assertEqual(role_deploy_modes(role, "web-svc-probe"), {"host": True})

    def test_a_stack_role_without_a_declaration_falls_back_on_its_shape(self) -> None:
        role = self.fx.write("web-svc-probe", "probe:\n  enabled: true\n", stack=True)
        self.assertEqual(
            role_deploy_modes(role, "web-svc-probe"),
            {"compose": True, "swarm": True},
        )

    def test_a_stackless_role_without_a_declaration_is_host_only(self) -> None:
        role = self.fx.write("web-svc-probe", "probe:\n  enabled: true\n", stack=False)
        self.assertEqual(role_deploy_modes(role, "web-svc-probe"), {"host": True})

    def test_a_disabled_declared_mode_is_offered_as_false(self) -> None:
        role = self.fx.write(
            "web-svc-probe",
            """
            probe:
              modes:
                compose:
                  enabled: true
                swarm:
                  enabled: false
            """,
            stack=True,
        )
        self.assertEqual(
            role_deploy_modes(role, "web-svc-probe"),
            {"compose": True, "swarm": False},
        )


if __name__ == "__main__":
    unittest.main()
