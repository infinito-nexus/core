"""Integration guard: a disabled provider takes the entries gated on its
presence along, even where a variant pins them on.

``web-app-nextcloud#0`` pins ``services.talk.enabled: true``, while the role's
own gate is ``'web-svc-coturn' in group_names``. On a tor-only row the CI
planner disables ``web-svc-coturn``, which serves clearnet only. Talk then stayed
on without a TURN server, and the role's "Talk has the TURN server its calls
relay through" assert failed on every such row.

The test builds that row's inventory the way the dev deploy does (planner
include, ``disable`` tokens, orphan prune, variant bake, provision disabler) and
renders the real applications payload against the row's groups: whenever the
spreed addon is on, the standalone TURN server it hands out must be on too.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

from cli.administration.deploy.development.inventory import (
    _build_services_overrides_for_round,
    _resolve_variant_payloads,
    plan_dev_inventory_matrix,
    prune_orphans_after_disable,
)
from cli.administration.inventory.provision.services_disabler import (
    apply_services_disabled_from_env,
    find_provider_roles,
    parse_services_disabled,
    reconcile_services_disabled_from_env,
)
from utils.cache import _reset_cache_for_tests
from utils.cache.applications import get_merged_applications
from utils.cache.yaml import dump_yaml, load_yaml_any
from utils.github.variant.network import TOR, disabled_services

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
APP = "web-app-nextcloud"
TURN_PROVIDER = "web-svc-coturn"
VARIANT = 0


def _provision_tor_row(workdir: Path) -> tuple[list[str], dict]:
    """Provision the tor-only row of ``APP#VARIANT``.

    Args:
        workdir: directory the row's ``devices.yml`` and host_vars go to.

    Returns:
        the row's inventory groups and its host_vars ``applications``.
    """
    plan = plan_dev_inventory_matrix(
        roles_dir=str(ROLES_DIR), primary_apps=[APP], base_inventory_dir="plan"
    )
    round_index, _dir, round_variants, include, _purge = plan[VARIANT]
    disable = disabled_services(TOR, include)
    if TURN_PROVIDER not in disable.split():
        raise AssertionError(
            f"the tor-only row of {APP}#{VARIANT} no longer disables {TURN_PROVIDER} "
            f"(disable={disable!r}); this guard reproduces nothing"
        )
    disabled = find_provider_roles(parse_services_disabled(disable), ROLES_DIR)
    include, _pruned = prune_orphans_after_disable(
        include=include,
        primary_apps=[APP],
        disabled_app_ids=set(disabled.values()),
        services_overrides=_build_services_overrides_for_round(
            roles_dir=str(ROLES_DIR),
            round_index=round_index,
            primary_app_variants={APP: round_variants[APP]},
        ),
    )
    payloads = _resolve_variant_payloads(
        roles_dir=str(ROLES_DIR), include=include, active_variants=round_variants
    )
    host_vars = workdir / "localhost.yml"
    devices = workdir / "devices.yml"
    dump_yaml(host_vars, {"applications": json.loads(json.dumps(payloads))})
    dump_yaml(
        devices,
        {"all": {"children": {app: {"hosts": {"localhost": {}}} for app in include}}},
    )
    with (
        patch.dict(os.environ, {"disable": disable}),
        contextlib.redirect_stdout(io.StringIO()),
    ):
        reconcile_services_disabled_from_env(host_vars, ROLES_DIR)
        apply_services_disabled_from_env(
            host_vars, roles_dir=ROLES_DIR, inventory_file=devices
        )
    groups = sorted(load_yaml_any(devices)["all"]["children"])
    return groups, load_yaml_any(host_vars)["applications"]


class TestDisabledProviderDependents(unittest.TestCase):
    def tearDown(self) -> None:
        _reset_cache_for_tests()

    def test_talk_hands_out_a_turn_server_on_the_tor_row(self) -> None:
        with TemporaryDirectory() as tmp:
            groups, applications = _provision_tor_row(Path(tmp))
        _reset_cache_for_tests()
        rendered = get_merged_applications(
            variables={
                "ansible_facts": {"os_family": "Debian"},
                "ansible_connection": "local",
                "inventory_hostname": "localhost",
                "group_names": groups,
                "applications": applications,
            },
            roles_dir=str(ROLES_DIR),
            templar=Templar(loader=DataLoader()),
        )[APP]

        spreed = rendered["addons"]["spreed"]["enabled"]
        turn = rendered["services"]["talk"]["turn_server"]["standalone_enabled"]

        self.assertIsInstance(spreed, bool)
        self.assertIsInstance(turn, bool)
        self.assertFalse(
            spreed and not turn,
            f"{APP}#{VARIANT} on a tor-only row runs Talk (spreed enabled) while "
            f"{TURN_PROVIDER} is out of the inventory, so Talk hands out no TURN "
            "server and the role's TURN assert fails",
        )


if __name__ == "__main__":
    unittest.main()
