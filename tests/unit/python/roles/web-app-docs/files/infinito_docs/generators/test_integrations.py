from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from utils.cache.files import read_text
from utils.roles.mapping import (
    ROLE_DIR_META_ADDONS,
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
)

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

integrations = importlib.import_module("infinito_docs.generators.integrations")

SSO_GATE = "sso:\n  enabled: \"{{ 'web-app-keycloak' in group_names }}\"\n"
JIRA_KEY = "jira:\n  enabled: false\n"
JIRA_EOL = "jira:\n  enabled: false\n  lifecycle: eol\n"


def _role(roles_dir: Path, name: str, services: str = "", addons=None) -> Path:
    """Create one role directory below ``roles_dir``.

    Args:
        roles_dir: the directory the role is created in.
        name: the role name.
        services: body of ``meta/services.yml``; omitted when empty.
        addons: ``{file stem: body}`` written under ``meta/addons/``.
    """
    role = roles_dir / name
    meta = role / ROLE_FILE_META_MAIN
    meta.parent.mkdir(parents=True)
    meta.write_text("galaxy_info: {}\n", encoding="utf-8")
    if services:
        (role / ROLE_FILE_META_SERVICES).write_text(services, encoding="utf-8")
    for stem, body in (addons or {}).items():
        addon = role / ROLE_DIR_META_ADDONS / f"{stem}.yml"
        addon.parent.mkdir(parents=True, exist_ok=True)
        addon.write_text(body, encoding="utf-8")
    return role


class TestAxis(unittest.TestCase):
    def test_every_web_role_present_is_on_the_axis(self) -> None:
        """A hardcoded axis is what dropped 14 roles and kept a deleted one."""
        with TemporaryDirectory() as td:
            roles_dir = Path(td)
            _role(roles_dir, "web-app-alpha")
            _role(roles_dir, "web-svc-beta")
            self.assertEqual(
                integrations.axis(roles_dir), ["web-app-alpha", "web-svc-beta"]
            )

    def test_a_role_outside_the_web_prefixes_is_not_on_the_axis(self) -> None:
        with TemporaryDirectory() as td:
            roles_dir = Path(td)
            _role(roles_dir, "web-app-alpha")
            _role(roles_dir, "svc-db-postgres")
            self.assertEqual(integrations.axis(roles_dir), ["web-app-alpha"])

    def test_a_role_that_does_not_exist_cannot_appear(self) -> None:
        with TemporaryDirectory() as td:
            roles_dir = Path(td)
            _role(roles_dir, "web-app-alpha")
            self.assertNotIn("web-app-gone", integrations.axis(roles_dir))


class TestServiceTargets(unittest.TestCase):
    def test_a_key_resolves_to_the_role_its_gate_names(self) -> None:
        """``sso`` names no role; only its gate says the provider is Keycloak."""
        with TemporaryDirectory() as td:
            roles_dir = Path(td)
            _role(roles_dir, "web-app-alpha", services=SSO_GATE)
            _role(roles_dir, "web-app-keycloak")
            targets = integrations.service_targets(
                roles_dir, integrations.axis(roles_dir)
            )
            self.assertEqual(targets["sso"], "web-app-keycloak")

    def test_a_key_that_is_an_entity_name_resolves_to_that_role(self) -> None:
        with TemporaryDirectory() as td:
            roles_dir = Path(td)
            _role(roles_dir, "web-app-alpha", services="matomo:\n  bond: 1\n")
            _role(roles_dir, "web-app-matomo")
            targets = integrations.service_targets(
                roles_dir, integrations.axis(roles_dir)
            )
            self.assertEqual(targets["matomo"], "web-app-matomo")

    def test_a_key_naming_no_role_on_the_axis_resolves_to_nothing(self) -> None:
        """A sidecar must not read as an integration with another role."""
        with TemporaryDirectory() as td:
            roles_dir = Path(td)
            _role(
                roles_dir,
                "web-app-alpha",
                services="redis:\n  enabled: \"{{ 'svc-db-redis' in group_names }}\"\n",
            )
            targets = integrations.service_targets(
                roles_dir, integrations.axis(roles_dir)
            )
            self.assertNotIn("redis", targets)


class TestEdges(unittest.TestCase):
    def test_a_service_key_becomes_an_edge_to_its_provider(self) -> None:
        with TemporaryDirectory() as td:
            roles_dir = Path(td)
            role = _role(roles_dir, "web-app-alpha", services=SSO_GATE)
            _role(roles_dir, "web-app-keycloak")
            targets = integrations.service_targets(
                roles_dir, integrations.axis(roles_dir)
            )
            self.assertEqual(
                integrations.service_edges(role, targets),
                [("sso", "web-app-keycloak")],
            )

    def test_a_roles_own_entry_is_not_an_edge_to_itself(self) -> None:
        """``alpha:`` in ``web-app-alpha`` is the role's own container."""
        with TemporaryDirectory() as td:
            roles_dir = Path(td)
            role = _role(roles_dir, "web-app-alpha", services="alpha:\n  bond: 1\n")
            targets = integrations.service_targets(
                roles_dir, integrations.axis(roles_dir)
            )
            self.assertEqual(integrations.service_edges(role, targets), [])

    def test_an_addon_bridge_becomes_an_edge(self) -> None:
        with TemporaryDirectory() as td:
            roles_dir = Path(td)
            role = _role(
                roles_dir,
                "web-app-alpha",
                services=SSO_GATE,
                addons={"openid_connect": "bridges:\n  - sso\n"},
            )
            _role(roles_dir, "web-app-keycloak")
            targets = integrations.service_targets(
                roles_dir, integrations.axis(roles_dir)
            )
            self.assertEqual(
                integrations.addon_edges(role, targets),
                [("openid_connect", "sso", "web-app-keycloak")],
            )

    def test_an_addon_without_a_bridge_is_not_an_edge(self) -> None:
        with TemporaryDirectory() as td:
            roles_dir = Path(td)
            role = _role(
                roles_dir,
                "web-app-alpha",
                addons={"docker_manager": "mechanism: plugin\n"},
            )
            targets = integrations.service_targets(
                roles_dir, integrations.axis(roles_dir)
            )
            self.assertEqual(integrations.addon_edges(role, targets), [])

    def test_a_role_without_any_integration_has_no_edges(self) -> None:
        """A role with neither file must not raise on the missing paths."""
        with TemporaryDirectory() as td:
            roles_dir = Path(td)
            role = _role(roles_dir, "web-app-alpha")
            targets = integrations.service_targets(
                roles_dir, integrations.axis(roles_dir)
            )
            self.assertEqual(integrations.service_edges(role, targets), [])
            self.assertEqual(integrations.addon_edges(role, targets), [])


class TestEolTargets(unittest.TestCase):
    def test_a_role_whose_primary_is_eol_is_reported(self) -> None:
        with TemporaryDirectory() as td:
            roles_dir = Path(td)
            _role(roles_dir, "web-app-alpha", services=JIRA_KEY)
            _role(roles_dir, "web-app-jira", services=JIRA_EOL)
            self.assertEqual(
                integrations.eol_roles(roles_dir, integrations.axis(roles_dir)),
                {"web-app-jira"},
            )

    def test_a_role_without_a_lifecycle_is_not_reported(self) -> None:
        with TemporaryDirectory() as td:
            roles_dir = Path(td)
            _role(roles_dir, "web-app-alpha", services=SSO_GATE)
            _role(roles_dir, "web-app-keycloak")
            self.assertEqual(
                integrations.eol_roles(roles_dir, integrations.axis(roles_dir)),
                set(),
            )

    def test_only_an_eol_target_carries_the_mark(self) -> None:
        self.assertEqual(
            integrations.render_target("web-app-jira", {"web-app-jira"}),
            "``web-app-jira`` (end of life)",
        )
        self.assertEqual(
            integrations.render_target("web-app-keycloak", {"web-app-jira"}),
            "``web-app-keycloak``",
        )


class TestRenderedEolPages(unittest.TestCase):
    """A declared edge to an EOL partner must not read as a live integration."""

    def _render(self) -> dict[str, str]:
        with TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            _role(
                roles_dir,
                "web-app-alpha",
                services=JIRA_KEY + SSO_GATE,
                addons={"jira": "bridges:\n  - jira\n"},
            )
            _role(roles_dir, "web-app-jira", services=JIRA_EOL)
            _role(roles_dir, "web-app-keycloak")
            output = Path(td) / "out"
            integrations.generate(roles_dir, output)
            return {
                name: read_text(str(output / f"{name}.rst"))
                for name in ("overview", "services", "addons")
            }

    def test_the_overview_marks_the_eol_partner(self) -> None:
        self.assertIn("   * ``web-app-jira`` (end of life)", self._render()["overview"])

    def test_the_service_page_marks_the_eol_provider(self) -> None:
        self.assertIn(
            "   * ``jira`` -> ``web-app-jira`` (end of life)",
            self._render()["services"],
        )

    def test_the_addon_page_marks_the_eol_provider(self) -> None:
        self.assertIn(
            "   * ``jira``: ``jira`` -> ``web-app-jira`` (end of life)",
            self._render()["addons"],
        )

    def test_a_live_partner_on_the_same_page_stays_unmarked(self) -> None:
        self.assertIn(
            "   * ``sso`` -> ``web-app-keycloak``\n", self._render()["services"]
        )

    def test_every_page_explains_the_mark(self) -> None:
        for page in self._render().values():
            self.assertIn("``(end of life)``", page)


class TestRenderedPages(unittest.TestCase):
    def _render(self) -> dict[str, str]:
        with TemporaryDirectory() as td:
            roles_dir = Path(td) / "roles"
            roles_dir.mkdir()
            _role(
                roles_dir,
                "web-app-alpha",
                services=SSO_GATE,
                addons={"openid_connect": "bridges:\n  - sso\n"},
            )
            _role(roles_dir, "web-app-keycloak")
            _role(roles_dir, "web-svc-beta")
            output = Path(td) / "out"
            count = integrations.generate(roles_dir, output)
            pages = {
                name: read_text(str(output / f"{name}.rst"))
                for name in ("overview", "services", "addons")
            }
        self.assertEqual(count, 3)
        return pages

    def test_every_role_is_named_on_every_page(self) -> None:
        for page in self._render().values():
            self.assertIn("``web-app-alpha``", page)
            self.assertIn("``web-app-keycloak``", page)
            self.assertIn("``web-svc-beta``", page)

    def test_the_service_page_names_the_key_and_the_provider(self) -> None:
        self.assertIn(
            "   * ``sso`` -> ``web-app-keycloak``", self._render()["services"]
        )

    def test_the_addon_page_names_the_addon_the_key_and_the_provider(self) -> None:
        self.assertIn(
            "   * ``openid_connect``: ``sso`` -> ``web-app-keycloak``",
            self._render()["addons"],
        )

    def test_the_overview_names_the_reached_role_once(self) -> None:
        """The key and the add-on reach the same role and must not list it twice."""
        overview = self._render()["overview"]
        block = overview.split("``web-app-alpha``\n")[1].split("\n\n")[0]
        self.assertEqual(block, "   * ``web-app-keycloak``")

    def test_a_role_without_edges_keeps_a_definition_body(self) -> None:
        """An empty body would break the definition list it sits in."""
        self.assertIn("``web-svc-beta``\n   None.", self._render()["overview"])


if __name__ == "__main__":
    unittest.main()
