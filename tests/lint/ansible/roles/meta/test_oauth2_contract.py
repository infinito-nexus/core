"""Lint guard for the per-role oauth2 service-block contract.

When a role's ``meta/services.yml`` declares an ``oauth2:`` block whose
``enabled`` field is anything other than literal ``false`` (i.e. it MAY
resolve truthy at runtime, including the common
``"{{ 'web-app-keycloak' in group_names }}"`` form), the role MUST also
carry every key that the oauth2-proxy front-proxy template chain reads
back. Missing fields surface only at deploy time as opaque
``lookup('config', application_id, '...') failed`` errors — exactly the
trap that hit ``web-app-shopware`` on the Bundle 2 V0 deploy in this
repo.

Required for a role with oauth2 potentially enabled:
  * ``oauth2.origin.host`` — non-empty string, names the upstream service
    the oauth2-proxy forwards authenticated traffic to.
  * ``oauth2.origin.port`` — non-empty value (string or int), the
    upstream service port.
  * ``<entity>.ports.local.oauth2`` — non-empty int, the local port the
    role's own oauth2-proxy listens on (consumed by
    ``sys-stk-front-proxy/templates/vhost/basic.conf.j2`` via
    ``lookup('config', application_id, 'services.<entity>.ports.local.oauth2')``).
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

import yaml

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.entity_name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

ROLES_DIR = PROJECT_ROOT / "roles"


def _load_services(role_dir: Path):
    services_path = role_dir / ROLE_FILE_META_SERVICES
    if not services_path.is_file():
        return None
    try:
        text = read_text(str(services_path))
    except UnicodeDecodeError:
        return None
    if not text.strip():
        return None
    try:
        return load_yaml_str(text)
    except yaml.YAMLError:
        return None


def _oauth2_potentially_enabled(oauth2_block) -> bool:
    """Treat oauth2 as potentially enabled unless `enabled` is literal false.

    Jinja-template strings (e.g. ``"{{ 'web-app-keycloak' in group_names }}"``)
    resolve truthy at runtime and therefore MUST satisfy the contract.
    """
    if not isinstance(oauth2_block, dict):
        return False
    enabled = oauth2_block.get("enabled", None)
    return not (
        enabled is False
        or (isinstance(enabled, str) and enabled.strip().lower() == "false")
    )


def _is_non_empty_string(value) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _is_non_empty_scalar(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        return value.strip() != ""
    return False


class TestOauth2RoleContract(unittest.TestCase):
    def test_oauth2_origin_and_port_present_when_enabled(self):
        violations: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            if not role_dir.is_dir():
                continue
            role_name = role_dir.name
            services = _load_services(role_dir)
            if not isinstance(services, dict):
                continue
            oauth2_block = services.get("oauth2")
            if oauth2_block is None:
                continue
            if not _oauth2_potentially_enabled(oauth2_block):
                continue

            # Required: oauth2.origin.{host,port}
            origin = (
                oauth2_block.get("origin") if isinstance(oauth2_block, dict) else None
            )
            if not isinstance(origin, dict):
                violations.append(
                    f"{role_name}: meta/services.yml.oauth2 has `enabled` truthy "
                    f'but no `origin` map — add `origin: {{ host: <svc>, port: "<port>" }}`.'
                )
            else:
                host = origin.get("host")
                port = origin.get("port")
                if not _is_non_empty_string(host):
                    violations.append(
                        f"{role_name}: meta/services.yml.oauth2.origin.host is missing or empty."
                    )
                if not _is_non_empty_scalar(port):
                    violations.append(
                        f"{role_name}: meta/services.yml.oauth2.origin.port is missing or empty."
                    )

            # Required: <entity>.ports.local.oauth2 — the role's local
            # oauth2-proxy listen port consumed by sys-stk-front-proxy.
            entity = get_entity_name(role_name)
            if not entity:
                continue
            entity_block = services.get(entity)
            if not isinstance(entity_block, dict):
                violations.append(
                    f"{role_name}: meta/services.yml has oauth2 enabled but no "
                    f"`{entity}:` entity block to host the local port map."
                )
                continue
            ports_local = (
                entity_block.get("ports", {}).get("local", {})
                if isinstance(entity_block.get("ports"), dict)
                else {}
            )
            if not isinstance(ports_local, dict) or "oauth2" not in ports_local:
                violations.append(
                    f"{role_name}: meta/services.yml.{entity}.ports.local.oauth2 "
                    "is missing — required because oauth2 is potentially enabled. "
                    "Add `oauth2: <16xxx-port>` next to the existing `http:` port."
                )
                continue
            if not isinstance(ports_local["oauth2"], int):
                violations.append(
                    f"{role_name}: meta/services.yml.{entity}.ports.local.oauth2 "
                    f"must be an int port, got {ports_local['oauth2']!r}."
                )

        if violations:
            self.fail(
                "Roles with oauth2 enabled are missing required service-block fields:\n"
                + "\n".join(f"  - {v}" for v in violations)
                + "\n\nThese fields are consumed at deploy time by:\n"
                + "  - roles/sys-stk-front-proxy/tasks/main.yml "
                + "(lookup('config', application_id, 'services.<entity>.ports.local.oauth2'))\n"
                + "  - roles/web-app-oauth2-proxy/templates/oauth2-proxy-keycloak.cfg.j2 "
                + "(lookup('config', application_id, 'services.oauth2.origin.host')).\n"
                + "Reference shape: roles/web-app-kix/meta/services.yml."
            )


if __name__ == "__main__":
    unittest.main()
