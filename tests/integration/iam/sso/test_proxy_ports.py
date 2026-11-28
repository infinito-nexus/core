"""Guard: every role with ``services.sso.flavor: oauth2`` AND ``sso.enabled``
potentially truthy in ``meta/services.yml`` MUST allocate an SSO-proxy
listen port via ``<service>.ports.local.sso: <port>`` in the same file.

Background
==========
When a role's SSO flavor is oauth2 (i.e. the oauth2-proxy sidecar fronts
the upstream), the proxy needs a unique local port to listen on. The
port is declared under one of the role's service entries'
``ports.local.sso`` key (typically the role's primary service block).
Without this, the proxy renders without a port and rollout silently
produces a half-wired vhost.

This is the renamed in-tree successor of the legacy oauth2/oidc-split
proxy-ports guard; the contract ("oauth2-flavored SSO roles MUST
allocate an SSO-proxy port") is unchanged.

An application served on several networks runs one oauth2-proxy per network
(``sso.proxy_instances``), and each further network's instance binds
``ports.local.sso_<label>`` of the entity the keycloak ``sso_proxy`` templates
read (``application_id | entity_name``). A role whose ``tor`` service and
reachability let it serve clearnet and onion together therefore MUST declare
that port too, or the onion vhost fails to render in ``multi`` mode.
"""

from __future__ import annotations

import copy
import unittest

from utils.cache.yaml import load_yaml
from utils.networks.instances import labelled
from utils.networks.reachability import (
    MULTI,
    allowed_networks,
    effective_networks,
    network,
)
from utils.roles.applications.services.sso import is_potentially_enabled
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_META_NETWORKS, ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"


def _gated_services(role_path) -> dict | None:
    """Args:
        role_path: the role directory.

    Returns:
        The role's ``meta/services.yml`` when oauth2-proxy may front it, else None.
    """
    services_file = role_path / ROLE_FILE_META_SERVICES
    if not services_file.exists():
        return None
    services = load_yaml(services_file, default_if_missing={})
    sso = services.get("sso") if isinstance(services, dict) else None
    if not isinstance(sso, dict) or sso.get("flavor") != "oauth2":
        return None
    return services if is_potentially_enabled(sso.get("enabled")) else None


def missing_instance_ports(role: str, services: dict, networks: dict) -> list[str]:
    """Args:
        role: the application id.
        services: the role's ``meta/services.yml``.
        networks: the role's ``meta/networks.yml``.

    Returns:
        ``ports.local.<key>`` of every oauth2-proxy instance past the canonical
        one that the role's entity leaves undeclared on a ``multi`` node.
    """
    tor = services.get("tor")
    tor_enabled = isinstance(tor, dict) and is_potentially_enabled(tor.get("enabled"))
    allowed, single_mode = allowed_networks(
        {"networks": networks}, tor_enabled=tor_enabled, app=role
    )
    served = effective_networks(MULTI, allowed, single_mode, app=role)
    entity = services.get(entity_name(role))
    ports = entity.get("ports") if isinstance(entity, dict) else None
    local = ports.get("local") if isinstance(ports, dict) else None
    local = local if isinstance(local, dict) else {}
    keys = [labelled("sso", network(name).label, "_") for name in served[1:]]
    return [key for key in keys if local.get(key) is None]


def _has_sso_port(services: dict) -> bool:
    """Return True iff any service entry declares ``ports.local.sso``."""
    for value in services.values():
        if not isinstance(value, dict):
            continue
        ports = value.get("ports")
        if not isinstance(ports, dict):
            continue
        local = ports.get("local")
        if not isinstance(local, dict):
            continue
        if local.get("sso") is not None:
            return True
    return False


class TestSsoProxyPorts(unittest.TestCase):
    def test_oauth2_flavor_role_has_proxy_port(self) -> None:
        failures: list[str] = []
        for role_path in sorted(ROLES_DIR.iterdir()):
            if not role_path.is_dir():
                continue
            services_file = role_path / ROLE_FILE_META_SERVICES
            if not services_file.exists():
                continue

            try:
                services = load_yaml(services_file, default_if_missing={})
            except (ValueError, OSError) as error:
                failures.append(
                    f"{role_path.name}: failed to load meta/services.yml ({error})"
                )
                continue

            sso = services.get("sso") if isinstance(services, dict) else None
            if not isinstance(sso, dict):
                continue
            if sso.get("flavor") != "oauth2":
                continue
            if not is_potentially_enabled(sso.get("enabled")):
                continue

            if not _has_sso_port(services):
                failures.append(
                    f"{role_path.name}: services.sso.flavor=oauth2 with "
                    f"enabled potentially truthy but no service declares "
                    f"ports.local.sso. Add `sso: <port>` under the primary "
                    f"service's `ports.local:` block in meta/services.yml."
                )

        if failures:
            self.fail(
                "Roles with sso.flavor=oauth2 must allocate an SSO-proxy port:\n"
                + "\n".join(f"  - {entry}" for entry in failures)
            )

    def test_every_network_instance_of_the_proxy_has_a_port(self) -> None:
        failures: list[str] = []
        for role_path in sorted(ROLES_DIR.iterdir()):
            services = _gated_services(role_path) if role_path.is_dir() else None
            if services is None:
                continue
            networks = load_yaml(
                role_path / ROLE_FILE_META_NETWORKS, default_if_missing={}
            )
            failures.extend(
                f"{role_path.name}: services.{entity_name(role_path.name)}"
                f".ports.local.{key} is missing"
                for key in missing_instance_ports(role_path.name, services, networks)
            )
        if failures:
            self.fail(
                "An oauth2-gated role served on clearnet and onion runs one proxy "
                "per network; allocate each further port with `cli contributing "
                "network ports suggest --scope local --category <key>`:\n"
                + "\n".join(f"  - {entry}" for entry in failures)
            )

    def test_negative_control_an_onion_served_role_without_its_port_fails(
        self,
    ) -> None:
        role = "web-app-worldmonitor"
        services = copy.deepcopy(_gated_services(ROLES_DIR / role))
        self.assertIsNotNone(services)
        networks = load_yaml(
            ROLES_DIR / role / ROLE_FILE_META_NETWORKS, default_if_missing={}
        )
        self.assertEqual(missing_instance_ports(role, services, networks), [])
        del services[entity_name(role)]["ports"]["local"]["sso_onion"]
        self.assertEqual(
            missing_instance_ports(role, services, networks), ["sso_onion"]
        )
        services["tor"]["enabled"] = False
        self.assertEqual(missing_instance_ports(role, services, networks), [])


if __name__ == "__main__":
    unittest.main()
