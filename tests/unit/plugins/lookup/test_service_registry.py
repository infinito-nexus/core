from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import patch

from plugins.lookup.service_registry import LookupModule
from utils.cache.yaml import dump_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)


def _mk_role(
    roles_dir: Path,
    role_name: str,
    application_id: str,
    services_payload: dict,
) -> None:
    role_dir = roles_dir / role_name
    (role_dir / "vars").mkdir(parents=True)
    (role_dir / "meta").mkdir(parents=True)
    (role_dir / ROLE_FILE_VARS_MAIN).write_text(
        dump_yaml_str({"application_id": application_id}),
        encoding="utf-8",
    )
    (role_dir / ROLE_FILE_META_SERVICES).write_text(
        dump_yaml_str(services_payload),
        encoding="utf-8",
    )
    (role_dir / ROLE_FILE_META_MAIN).write_text(
        "galaxy_info: {}\n",
        encoding="utf-8",
    )


class TestServiceRegistryOrdered(unittest.TestCase):
    def _roles_dir(self, td: str) -> Path:
        roles_dir = Path(td)
        _mk_role(
            roles_dir,
            "web-app-mailu",
            "web-app-mailu",
            {"mailu": {"enabled": True, "shared": True, "provides": "email"}},
        )
        _mk_role(
            roles_dir,
            "web-app-keycloak",
            "web-app-keycloak",
            {
                "keycloak": {
                    "enabled": True,
                    "shared": True,
                    "provides": "sso",
                    "run_after": ["web-app-mailu"],
                }
            },
        )
        _mk_role(
            roles_dir,
            "web-app-prometheus",
            "web-app-prometheus",
            {
                "prometheus": {
                    "enabled": "{{ 'web-app-prometheus' in group_names }}",
                    "shared": "{{ 'web-app-prometheus' in group_names }}",
                    "run_after": ["web-app-keycloak"],
                }
            },
        )
        return roles_dir

    def test_ordered_ignores_play_applications_and_host_variables(self):
        """'ordered' feeds the sys-service-loader loop, so it MUST NOT
        depend on per-host rendered applications: hosts whose group_names
        flip dynamic `shared` flags would otherwise compute divergent
        lists, and Ansible interleaves the loop includes in
        result-arrival order (consumers deploy before their engines)."""
        with tempfile.TemporaryDirectory() as td:
            roles_dir = self._roles_dir(td)
            with patch("plugins.lookup.service_registry.lookup_loader") as loader_mock:
                lm = LookupModule()
                lm._loader = mock.MagicMock()
                result = lm.run(
                    ["ordered"],
                    variables={"group_names": ["web-app-nextcloud"]},
                    roles_dir=str(roles_dir),
                )[0]
        loader_mock.get.assert_not_called()
        self.assertEqual(
            [entry["id"] for entry in result],
            ["email", "sso", "prometheus"],
        )

    def test_ordered_keeps_dynamic_flag_provider_as_candidate(self):
        """A provider whose `shared` is the dynamic group_names form stays
        in the ordered list; load_service.yml's per-host `when` decides
        whether it actually loads."""
        with tempfile.TemporaryDirectory() as td:
            roles_dir = self._roles_dir(td)
            lm = LookupModule()
            lm._loader = mock.MagicMock()
            result = lm.run(["ordered"], variables={}, roles_dir=str(roles_dir))[0]
        by_id = {entry["id"]: entry for entry in result}
        self.assertIn("prometheus", by_id)
        self.assertEqual(by_id["prometheus"]["role"], "web-app-prometheus")
        self.assertLess(
            [e["id"] for e in result].index("sso"),
            [e["id"] for e in result].index("prometheus"),
        )

    def test_mapping_mode_uses_play_applications(self):
        applications = {
            "web-app-mailu": {
                "services": {
                    "mailu": {"enabled": True, "shared": True, "provides": "email"}
                }
            }
        }
        with patch("plugins.lookup.service_registry.lookup_loader") as loader_mock:
            loader_mock.get.return_value = mock.MagicMock(
                run=lambda *_a, **_k: [applications]
            )
            lm = LookupModule()
            lm._loader = mock.MagicMock()
            registry = lm.run([], variables={"group_names": []})[0]
        loader_mock.get.assert_called_once()
        self.assertEqual(registry["email"]["role"], "web-app-mailu")
