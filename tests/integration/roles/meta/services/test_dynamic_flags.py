"""Integration guard: every ``services.<key>.enabled`` and
``services.<key>.shared`` value in ``roles/*/meta/services.yml`` MUST
be set dynamically via a Jinja ``in group_names`` expression that
references the role which provides that service.

Rationale
---------

The inventory builder is moving away from ``run_after`` as the
dependency-injection mechanism (see
``tests/integration/roles/dependencies/run_after/test_services_explicit.py``).
The single source of truth for "what gets co-deployed with this role"
is the per-role ``services`` map. To keep that map honest across hosts
with different group-membership profiles, ``enabled`` and ``shared``
MUST resolve from the host's ``group_names`` rather than being
hard-coded literals.

Required shape
--------------

For a service-key ``<key>`` whose primary provider role in the
project-wide service registry is ``<role>``::

    <key>:
      enabled: "{{ '<role>' in group_names }}"
      shared:  "{{ '<role>' in group_names }}"

Provided service keys (via the providing role's primary-entity
``provides:`` list) reference the providing role rather than the
service key itself. ``web-app-keycloak``'s primary entity declares
``provides: [sso]`` so ``services.sso.*`` in any consumer MUST
reference ``web-app-keycloak``::

    sso:
      enabled: "{{ 'web-app-keycloak' in group_names }}"
      shared:  "{{ 'web-app-keycloak' in group_names }}"
      flavor:  oidc   # or oauth2 / saml

Exemptions
----------

Two suppression placements are accepted, each with its own scope:

1. **Comment block above the service key** suppresses BOTH ``enabled``
   and ``shared`` for that service. Use this when the entire block
   stays literal (e.g. ``css``, where both flags are wired by the
   include layer)::

       # nocheck: dynamic-flag
       css:
         enabled: true
         shared: true

2. **Same line as the flag** suppresses just that one flag. Use this
   for databases, where ``enabled: true`` reflects "this role uses
   the database engine" (a static fact about the role's needs) but
   ``shared`` still resolves dynamically from group membership::

       mariadb:
         enabled: true  # nocheck: dynamic-flag
         shared: "{{ 'svc-db-mariadb' in group_names }}"
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.registry import (
    build_covered_key_to_role,
    build_role_to_primary_service_key,
    build_service_registry_from_roles_dir,
)
from utils.roles.entity.name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"

_RULE = "dynamic-flag"


def _suppressed_top_level_keys(file_path: Path) -> set[str]:
    """Return the set of top-level service keys whose preceding comment
    block carries a ``# nocheck: dynamic-flag`` (or ``# noqa:``) marker.

    A blank line between the marker and the key breaks the association,
    matching the catalog's "comment block above" semantic.
    """
    exceptions: set[str] = set()
    pending = False
    for raw_line in read_text(str(file_path)).splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("#"):
            if line_has_rule(raw_line, _RULE):
                pending = True
            continue
        if not stripped:
            pending = False
            continue
        is_top_level = not raw_line.startswith((" ", "\t"))
        if pending and is_top_level and ":" in stripped:
            key = stripped.split(":", 1)[0].strip()
            if key:
                exceptions.add(key)
        pending = False
    return exceptions


def _suppressed_inline_flags(file_path: Path) -> set[tuple[str, str]]:
    """Return ``{(service_key, flag_name)}`` for every flag whose own
    line carries ``# nocheck: dynamic-flag`` (or ``# noqa: ...``).
    This is the per-flag opt-out used by databases — ``enabled: true``
    stays literal while ``shared`` continues to resolve via
    ``in group_names``.
    """
    result: set[tuple[str, str]] = set()
    current_key: str | None = None
    for raw_line in read_text(str(file_path)).splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not raw_line.startswith((" ", "\t")) and ":" in stripped:
            current_key = stripped.split(":", 1)[0].strip() or None
            continue
        if current_key and ":" in stripped:
            head = stripped.split(":", 1)[0].strip()
            if head in {"enabled", "shared"} and line_has_rule(raw_line, _RULE):
                result.add((current_key, head))
    return result


# Consumer ``email`` blocks reference the MAIL_PROVIDER indirection variable
# instead of a concrete provider role (Stalwart <-> Mailu is a one-var switch).
_MAIL_PROVIDER_INDIRECTION = "MAIL_PROVIDER in group_names"


def _references_role_in_group_names(value, role_name: str) -> bool:
    """Return True iff *value* is a Jinja string of the shape
    ``{{ '<role_name>' in group_names }}`` (single or double quotes)."""
    if not isinstance(value, str):
        return False
    if "in group_names" not in value:
        return False
    return f"'{role_name}'" in value or f'"{role_name}"' in value


class TestServicesDynamicFlags(unittest.TestCase):
    def test_enabled_and_shared_use_in_group_names(self):
        registry = build_service_registry_from_roles_dir(ROLES_DIR)
        role_to_primary_key = build_role_to_primary_service_key(registry)
        primary_key_to_role = {key: role for role, key in role_to_primary_key.items()}
        covered_key_to_role = build_covered_key_to_role(registry)

        offenders: list[str] = []
        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            services_file = role_dir / ROLE_FILE_META_SERVICES
            if not services_file.is_file():
                continue
            try:
                data = load_yaml_any(services_file, default_if_missing={}) or {}
            except Exception as exc:
                offenders.append(f"{role_name}: YAML parse error: {exc}")
                continue
            if not isinstance(data, dict):
                continue

            block_exempt = _suppressed_top_level_keys(services_file)
            inline_exempt = _suppressed_inline_flags(services_file)
            own_entity = get_entity_name(role_name)

            for service_key, entry in data.items():
                if not isinstance(entry, dict):
                    continue
                if service_key in block_exempt:
                    continue
                if service_key == own_entity:
                    continue

                expected_role = covered_key_to_role.get(
                    service_key,
                    primary_key_to_role.get(service_key),
                )

                for flag in ("enabled", "shared"):
                    if flag not in entry:
                        continue
                    if (service_key, flag) in inline_exempt:
                        continue
                    value = entry[flag]
                    if not (isinstance(value, str) and "in group_names" in value):
                        offenders.append(
                            f"{role_name}: services.{service_key}.{flag}={value!r} "
                            f"is literal; replace with a Jinja "
                            f"\"{{{{ '<role>' in group_names }}}}\" expression "
                            f"(or add a `# nocheck: {_RULE}` comment above "
                            f"`{service_key}:` for legitimate exceptions like "
                            f"databases)."
                        )
                        continue
                    # email slot references MAIL_PROVIDER, not a provider role.
                    if (
                        service_key == "email"
                        and isinstance(value, str)
                        and _MAIL_PROVIDER_INDIRECTION in value
                    ):
                        continue
                    if expected_role and not _references_role_in_group_names(
                        value, expected_role
                    ):
                        offenders.append(
                            f"{role_name}: services.{service_key}.{flag}={value!r} "
                            f"must reference `'{expected_role}' in group_names`."
                        )

        if offenders:
            self.fail(
                f"services.<key>.enabled / shared MUST be dynamic "
                f"({_RULE}):\n" + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
