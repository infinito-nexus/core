from __future__ import annotations

import copy
import functools
import unittest
from typing import Any

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from utils.cache.applications import (
    get_merged_applications,
    get_variant_overrides_only,
)
from utils.domains.default_primary import default_domain_primary
from utils.roles.applications.status_codes import DEFAULT_OK, declared_status_codes
from utils.tests.caches import fresh_caches

from . import PROJECT_ROOT

APP = "web-svc-access-request"
DOMAIN = f"access.{default_domain_primary()}"
SIGN_IN_PAGE = 401


def _rendered(group_names: list[str], override: dict[str, Any]) -> dict[str, Any]:
    """
    Args:
        group_names: the groups of the host.
        override: the role's variant overlay, {} for a bare deploy such as the
            README replay on the shared target.

    Returns:
        The role's configuration as ``get_merged_applications`` renders it
        with a real Ansible templar.
    """
    applications = {APP: copy.deepcopy(override)} if override else {}
    variables = {"group_names": list(group_names), "applications": applications}
    templar = Templar(loader=DataLoader(), variables=dict(variables))
    templar.available_variables = dict(variables)
    with fresh_caches(files_changed=False):
        return get_merged_applications(variables=variables, templar=templar)[APP]


@functools.cache
def _deployments() -> dict[str, dict[str, Any]]:
    """
    Returns:
        ``{name: configuration}`` of the role bare on a host with and without
        Keycloak, and in every matrix variant on a host with Keycloak.
    """
    keycloak = [APP, "web-app-keycloak"]
    resolved = {
        "bare with keycloak": _rendered(keycloak, {}),
        "bare without keycloak": _rendered([APP], {}),
    }
    overrides = get_variant_overrides_only(roles_dir=PROJECT_ROOT / "roles")
    for index, override in enumerate(overrides[APP]):
        resolved[f"variant {index}"] = _rendered(keycloak, override)
    return resolved


def _expected_at_root(configuration: dict[str, Any]) -> list[int]:
    return declared_status_codes({APP: configuration}, APP, DOMAIN) or list(DEFAULT_OK)


class TestStatusCodesFollowTheGate(unittest.TestCase):
    def test_both_gate_states_are_deployed(self) -> None:
        states = {
            bool(configuration["services"]["sso"]["enabled"])
            for configuration in _deployments().values()
        }
        self.assertEqual(states, {True, False})

    def test_root_expects_the_sign_in_page_exactly_without_the_gate(self) -> None:
        for name, configuration in _deployments().items():
            gated = bool(configuration["services"]["sso"]["enabled"])
            with self.subTest(deployment=name, gated=gated):
                self.assertEqual(
                    _expected_at_root(configuration),
                    list(DEFAULT_OK) if gated else [SIGN_IN_PAGE],
                    "without the oauth2-proxy gate identity.py finds no session "
                    "header and app.py answers / with the 401 sign-in page",
                )

    def test_the_bare_replay_without_keycloak_expects_the_sign_in_page(self) -> None:
        self.assertEqual(
            _expected_at_root(_deployments()["bare without keycloak"]),
            [SIGN_IN_PAGE],
        )


if __name__ == "__main__":
    unittest.main()
