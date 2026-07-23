"""Lint guard for the per-role unified SSO service-block contract.

When a role's ``meta/services.yml`` declares an ``sso:`` block whose
``flavor`` is ``oauth2`` AND ``enabled`` is anything other than literal
``false`` (i.e. it MAY resolve truthy at runtime, including the common
``"{{ 'web-app-keycloak' in group_names }}"`` form), the role MUST also
carry every key that the SSO-proxy template chain reads back. Missing
fields surface only at deploy time as opaque
``lookup('config', application_id, '...') failed`` errors — exactly the
trap that hit ``web-app-shopware`` on the Bundle 2 V0 deploy.

Required for a role with ``services.sso.flavor: oauth2`` potentially
enabled:
  * ``sso.oauth2.origin.host`` — non-empty string, names the upstream
    service the SSO-proxy forwards authenticated traffic to.
  * ``sso.oauth2.origin.port`` — non-empty value (string or int), the
    upstream service port.
  * ``<entity>.ports.local.sso`` — non-empty int, the local port the
    role's own SSO-proxy listens on (consumed by
    ``sys-stk-front-proxy/templates/vhost/basic.conf.j2`` via
    ``lookup('config', application_id, 'services.<entity>.ports.local.sso')``).
"""

from __future__ import annotations

import unittest
from typing import TYPE_CHECKING

import yaml

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.applications.services.sso import is_potentially_enabled
from utils.roles.entity.name import get_entity_name
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


def _potentially_enabled(sso_block) -> bool:
    """Treat sso as potentially enabled unless `enabled` is literal false.

    Thin wrapper over the shared
    ``utils.roles.applications.services.sso.is_potentially_enabled``
    helper that adds the dict-shape guard required by this static
    YAML-tree scan.
    """
    if not isinstance(sso_block, dict):
        return False
    return is_potentially_enabled(sso_block.get("enabled"))


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


class TestSsoRoleContract(unittest.TestCase):
    def test_sso_oauth2_origin_and_port_present_when_enabled(self):
        violations: list[str] = []
        for role_dir in sorted(ROLES_DIR.iterdir()):
            if not role_dir.is_dir():
                continue
            role_name = role_dir.name
            services = _load_services(role_dir)
            if not isinstance(services, dict):
                continue
            sso_block = services.get("sso")
            if sso_block is None:
                continue
            if not _potentially_enabled(sso_block):
                continue
            if sso_block.get("flavor") != "oauth2":
                continue

            oauth2_sub = (
                sso_block.get("oauth2") if isinstance(sso_block, dict) else None
            )
            origin = oauth2_sub.get("origin") if isinstance(oauth2_sub, dict) else None
            if not isinstance(origin, dict):
                violations.append(
                    f"{role_name}: meta/services.yml.sso has `flavor: oauth2` "
                    f"and potentially-enabled SSO but no `oauth2.origin` map — "
                    f'add `oauth2: {{ origin: {{ host: <svc>, port: "<port>" }} }}`.'
                )
            else:
                host = origin.get("host")
                port = origin.get("port")
                if not _is_non_empty_string(host):
                    violations.append(
                        f"{role_name}: meta/services.yml.sso.oauth2.origin.host is missing or empty."
                    )
                if not _is_non_empty_scalar(port):
                    violations.append(
                        f"{role_name}: meta/services.yml.sso.oauth2.origin.port is missing or empty."
                    )

            entity = get_entity_name(role_name)
            if not entity:
                continue
            entity_block = services.get(entity)
            if not isinstance(entity_block, dict):
                violations.append(
                    f"{role_name}: meta/services.yml has sso.flavor=oauth2 "
                    f"enabled but no `{entity}:` entity block to host the "
                    f"local port map."
                )
                continue
            ports_local = (
                entity_block.get("ports", {}).get("local", {})
                if isinstance(entity_block.get("ports"), dict)
                else {}
            )
            if not isinstance(ports_local, dict) or "sso" not in ports_local:
                violations.append(
                    f"{role_name}: meta/services.yml.{entity}.ports.local.sso "
                    "is missing — required because sso.flavor=oauth2 is "
                    "potentially enabled. Add `sso: <16xxx-port>` next to "
                    "the existing `http:` port."
                )
                continue
            if not isinstance(ports_local["sso"], int):
                violations.append(
                    f"{role_name}: meta/services.yml.{entity}.ports.local.sso "
                    f"must be an int port, got {ports_local['sso']!r}."
                )

        if violations:
            self.fail(
                "Roles with sso.flavor=oauth2 enabled are missing required "
                "service-block fields:\n"
                + "\n".join(f"  - {v}" for v in violations)
                + "\n\nThese fields are consumed at deploy time by:\n"
                + "  - roles/sys-stk-front-proxy/tasks/main.yml "
                + "(lookup('config', application_id, 'services.<entity>.ports.local.sso'))\n"
                + "  - roles/web-app-keycloak/templates/sso_proxy/"
                + "oauth2-proxy-keycloak.cfg.j2 "
                + "(lookup('config', application_id, 'services.sso.oauth2.origin.host')).\n"
                + "Reference shape: roles/web-app-postmarks/meta/services.yml."
            )


if __name__ == "__main__":
    unittest.main()
