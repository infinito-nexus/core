"""Integration guard: every role listed under another role's
``meta/services.yml.<entity>.run_after`` MUST also be pulled in
explicitly via that role's own services block.

Future direction: the inventory builder is moving away from
``run_after`` as a dependency-injection mechanism. ``run_after`` keeps
its ordering-only role; "what gets co-deployed with this role" is
decided by the per-role ``services`` map. This test catches roles
whose ``run_after`` smuggles a dep in that no ``services.<key>``
entry covers.

Accepted shapes per ``run_after`` entry ``Y``:

1. The consuming role declares ``services.<key>`` where ``<key>`` is
   either the primary service key for ``Y`` in the project-wide
   service registry, OR a key listed in ``Y``'s primary entity
   ``covers:`` block (e.g. ``web-app-keycloak`` covers ``oauth2`` so
   ``services.oauth2`` satisfies ``run_after: [web-app-keycloak]``).
   The flag MUST be ``enabled: true`` AND ``shared: true``.
2. Or the same entry, with ``enabled`` / ``shared`` set to a Jinja
   conditional containing ``in group_names`` (e.g.
   ``"{{ 'web-app-foo' in group_names }}"``). The Jinja form lets a
   role conditionally pull a dep based on the live host's group
   membership while still encoding the dependency declaratively in
   ``services``.
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_role_to_covered_keys,
    build_service_registry_from_roles_dir,
    is_explicit_truth,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.meta_lookup import get_role_run_after

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"


def _load_services(role_dir: Path) -> dict:
    services_file = role_dir / ROLE_FILE_META_SERVICES
    if not services_file.is_file():
        return {}
    data = load_yaml_any(services_file, default_if_missing={})
    return data if isinstance(data, dict) else {}


class TestRunAfterServicesExplicit(unittest.TestCase):
    def test_run_after_entries_have_matching_service_flag(self):
        registry = build_service_registry_from_roles_dir(ROLES_DIR)
        # role -> [primary_key, *covers]. Each role's primary service
        # key plus its declared ``covers:`` (e.g. ``web-app-keycloak``
        # covers ``oauth2`` so a consumer's ``services.oauth2`` block
        # also satisfies ``run_after: [web-app-keycloak]``).
        role_to_candidate_keys = build_role_to_covered_keys(registry)

        offenders: list[str] = []
        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            try:
                run_after = get_role_run_after(role_dir, role_name=role_name)
            except Exception:
                continue
            if not run_after:
                continue

            services = _load_services(role_dir)

            for dep in run_after:
                candidate_keys = list(role_to_candidate_keys.get(dep, []))

                if not candidate_keys:
                    offenders.append(
                        f"{role_name}: run_after entry '{dep}' is not a "
                        f"service provider in the registry; either drop it "
                        f"from run_after or have '{dep}' export a shared "
                        f"service entity."
                    )
                    continue

                # A single legitimate entry is enough.
                matched = False
                near_misses: list[str] = []
                for key in candidate_keys:
                    entry = services.get(key)
                    if not isinstance(entry, dict):
                        near_misses.append(f"services.{key}: missing")
                        continue
                    if is_explicit_truth(entry.get("enabled")) and is_explicit_truth(
                        entry.get("shared")
                    ):
                        matched = True
                        break
                    near_misses.append(
                        f"services.{key}: enabled={entry.get('enabled')!r}, "
                        f"shared={entry.get('shared')!r}"
                    )

                if not matched:
                    expected_options = " | ".join(
                        f"services.{k}" for k in candidate_keys
                    )
                    offenders.append(
                        f"{role_name}: run_after lists '{dep}' but no "
                        f"matching enabled+shared entry in {expected_options}. "
                        f"Found: " + "; ".join(near_misses) + ". "
                        f"Declare one of those with enabled=true (or "
                        f"\"{{{{ '{dep}' in group_names }}}}\") and "
                        f"shared=true."
                    )

        if offenders:
            self.fail(
                "Implicit dependencies pulled via run_after only (req: every "
                "run_after entry must be matched by an explicit services "
                "flag):\n" + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
