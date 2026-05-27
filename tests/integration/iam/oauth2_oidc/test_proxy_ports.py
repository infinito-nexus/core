"""Guard: every role with ``oauth2.enabled: true`` in ``meta/services.yml``
MUST allocate an oauth2-proxy listen port via
``<service>.ports.local.oauth2: <port>`` in the same file.

Background
==========
When a role enables the oauth2-proxy frontend, the proxy needs a unique
local port to listen on. Per the port is declared under one of
the role's service entries' ``ports.local.oauth2`` key (typically the
role's primary service block). Without this the proxy renders without a
port and rollout silently produces a half-wired vhost.

This is the in-tree successor of ``test_proxy_ports.py`` that
``ed04dad5d`` removed when it deleted ``group_vars/all/09_ports.yml``
and the per-role ``config/main.yml``: the original test asserted the
contract against a centralised ports map that no longer exists. The
contract itself ("oauth2-using roles MUST allocate an oauth2-proxy
port") is unchanged; only the storage location moved.

Scope
=====
* Each ``roles/<role>/meta/services.yml`` is parsed via
  ``utils.cache.yaml.load_yaml`` so the file is read once per process
  and matches the loader policy enforced by
  ``tests/lint/repository/yaml/test_no_direct_calls.py``.
* Per the file root IS the services map (no
  ``compose.services`` wrapper), matching the convention pinned by
  ``tests/integration/iam/oauth2_oidc/test_mutual_exclusive.py``.
"""

from __future__ import annotations

import unittest

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"


def _has_oauth2_port(services: dict) -> bool:
    """Return True iff any service entry declares ``ports.local.oauth2``."""
    for value in services.values():
        if not isinstance(value, dict):
            continue
        ports = value.get("ports")
        if not isinstance(ports, dict):
            continue
        local = ports.get("local")
        if not isinstance(local, dict):
            continue
        if local.get("oauth2") is not None:
            return True
    return False


class TestOAuth2ProxyPorts(unittest.TestCase):
    def test_oauth2_enabled_role_has_proxy_port(self) -> None:
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

            oauth2 = services.get("oauth2") if isinstance(services, dict) else None
            if not (isinstance(oauth2, dict) and oauth2.get("enabled") is True):
                continue

            if not _has_oauth2_port(services):
                failures.append(
                    f"{role_path.name}: oauth2.enabled is true but no service "
                    f"declares ports.local.oauth2. Add `oauth2: <port>` under "
                    f"the primary service's `ports.local:` block in "
                    f"meta/services.yml."
                )

        if failures:
            self.fail(
                "Roles enabling oauth2 must allocate an oauth2-proxy port:\n"
                + "\n".join(f"  - {entry}" for entry in failures)
            )


if __name__ == "__main__":
    unittest.main()
