"""The translation bundle deploys every backend the gateway can route to.

``web-svc-translate`` names the backends its router may pick under
``router.order`` and turns each one on only while its engine role is in
``group_names``, so its ``meta/services.yml`` carries both halves of the
contract. ``utils.i18n.gateway.BUNDLE`` is the list ``make i18n-translate``
deploys. A routable backend whose role is missing from the bundle is one the
gateway is built for and never receives. The role's other gated services, from
sso to tor, are integrations rather than backends and stay out of this.

Nothing fails when that happens. The gateway keeps answering, the router falls
through to whatever is left, and the entries come back in the source language;
the damage predicate then discards them as untranslated. The languages only
that engine covers stay empty while every run reports success, which is how
``svc-ai-nllb-engine`` sat outside the bundle while seven catalogs took 0 of
358 offered entries.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.i18n.gateway import BUNDLE, ROLE, SERVICE_KEY
from utils.roles.mapping import ROLE_FILE_META_SERVICES

SERVICES_FILE = PROJECT_ROOT / "roles" / ROLE / ROLE_FILE_META_SERVICES
PROVIDER = re.compile(r"['\"](?P<role>[\w-]+)['\"]\s+in\s+group_names")


def providers() -> dict[str, str]:
    """Return each routable backend of the gateway mapped to the role it needs.

    Returns:
        backend name mapped to the role its ``enabled`` expression names.
    """
    services = load_yaml(SERVICES_FILE)
    routable = set(services[SERVICE_KEY]["router"]["order"])
    found = {}
    for key, entry in services.items():
        if not isinstance(entry, dict):
            continue
        name = key.removesuffix("-engine")
        if name not in routable:
            continue
        match = PROVIDER.search(str(entry.get("enabled", "")))
        if match:
            found[name] = match["role"]
    return found


class TestTranslationBundleCoversEveryBackend(unittest.TestCase):
    def test_every_gated_backend_role_is_deployed_by_the_bundle(self) -> None:
        missing = {key: role for key, role in providers().items() if role not in BUNDLE}

        report = "\n".join(
            f"  - {key}: {role}" for key, role in sorted(missing.items())
        )
        self.assertFalse(
            missing,
            f"{len(missing)} backend(s) of {ROLE} are gated on a role that "
            "utils.i18n.gateway.BUNDLE never deploys, so the gateway can route "
            f"to them but never gets them:\n{report}\n\n"
            "Add the role to BUNDLE, or drop the backend from the gateway.",
        )

    def test_the_services_file_still_gates_backends_on_a_role(self) -> None:
        self.assertTrue(
            providers(),
            "no enabled expression names a role any more, so this check has "
            "stopped reading the contract it guards",
        )


if __name__ == "__main__":
    unittest.main()
