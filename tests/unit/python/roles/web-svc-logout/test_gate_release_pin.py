from __future__ import annotations

import unittest

from ansible.module_utils.parsing.convert_bool import boolean

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.meta.scan import iter_role_dirs
from utils.roles.mapping import ROLE_FILE_META_SERVICES

LOGOUT_ROLE = PROJECT_ROOT / "roles" / "web-svc-logout"
FIRST_GATE_RELEASE = (1, 6, 0)
LAST_RELEASE_WITHOUT_GATE = "v1.5.2"


def release(version: str) -> tuple[int, ...]:
    """Return the numeric parts of a ``vMAJOR.MINOR.PATCH`` image tag.

    Args:
        version: the image tag, for example ``v1.5.2``.
    """
    return tuple(int(part) for part in version.removeprefix("v").split("."))


def gated_roles(services_by_role: dict[str, dict]) -> list[str]:
    """Return the roles whose back-channel receiver sits behind the logout gate.

    Args:
        services_by_role: role name -> the parsed ``meta/services.yml`` of that role.
    """
    return sorted(
        role
        for role, services in services_by_role.items()
        if boolean(
            ((services.get("sso") or {}).get("oidc") or {}).get(
                "backchannel_logout_gate"
            ),
            strict=False,
        )
    )


def pin_lacks_the_gate(logout_version: str, services_by_role: dict[str, dict]) -> bool:
    """Return whether a gated receiver depends on a conductor image without the gate.

    Args:
        logout_version: the universal-logout image tag web-svc-logout pins.
        services_by_role: role name -> the parsed ``meta/services.yml`` of that role.
    """
    return bool(gated_roles(services_by_role)) and (
        release(logout_version) < FIRST_GATE_RELEASE
    )


def repo_services() -> dict[str, dict]:
    return {
        role_dir.name: load_yaml_any(
            str(role_dir / ROLE_FILE_META_SERVICES), default_if_missing={}
        )
        or {}
        for role_dir in iter_role_dirs()
    }


def pinned_logout_version() -> str:
    services = load_yaml_any(str(LOGOUT_ROLE / ROLE_FILE_META_SERVICES))
    return services["logout"]["version"]


class TestTheConductorImageServesTheLogoutGate(unittest.TestCase):
    def setUp(self) -> None:
        self.services = repo_services()

    def test_the_repository_puts_receivers_behind_the_gate(self) -> None:
        self.assertIn("web-app-xwiki", gated_roles(self.services))

    def test_the_pinned_conductor_serves_the_gate_of_every_gated_receiver(
        self,
    ) -> None:
        self.assertFalse(
            pin_lacks_the_gate(pinned_logout_version(), self.services),
            f"universal-logout {pinned_logout_version()} serves no /backchannel/ route, "
            f"so Keycloak's logout tokens for {gated_roles(self.services)} end in a 404",
        )

    def test_a_pin_older_than_the_gate_release_is_caught(self) -> None:
        self.assertTrue(pin_lacks_the_gate(LAST_RELEASE_WITHOUT_GATE, self.services))

    def test_a_host_without_a_gated_receiver_needs_no_gate_release(self) -> None:
        ungated = {
            role: services
            for role, services in self.services.items()
            if role not in gated_roles(self.services)
        }
        self.assertFalse(pin_lacks_the_gate(LAST_RELEASE_WITHOUT_GATE, ungated))


if __name__ == "__main__":
    unittest.main()
