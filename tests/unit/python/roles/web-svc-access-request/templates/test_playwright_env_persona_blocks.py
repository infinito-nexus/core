from __future__ import annotations

import unittest
import unittest.mock as mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar, trust_as_template

from utils.cache.files import read_text

from . import PROJECT_ROOT

APP = "web-svc-access-request"
TEMPLATE = PROJECT_ROOT / "roles" / APP / "templates" / "playwright.env.j2"
SIGNED_IN_PERSONAS = ("PERSONA_ADMINISTRATOR_BLOCKED", "PERSONA_BIBER_BLOCKED")


class _SsoConfig(LookupBase):
    def __init__(self, sso_enabled: bool) -> None:
        super().__init__()
        self._sso_enabled = sso_enabled

    def run(self, terms, variables=None, **kwargs):
        if list(terms) != [APP, "services.sso.enabled"]:
            raise AssertionError(f"unexpected config lookup: {terms}")
        return [self._sso_enabled]


def render_persona_flags(sso_enabled: bool) -> dict[str, str]:
    """Render the persona opt-outs of the access-request Playwright env.

    Args:
        sso_enabled: the value ``services.sso.enabled`` of the role resolves to.

    Returns:
        Every ``PERSONA_*`` key the template declares, mapped to the value
        Ansible's templar renders for it.
    """
    rows = [
        row
        for row in read_text(str(TEMPLATE)).splitlines()
        if row.startswith("PERSONA_")
    ]
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "config":
            return _SsoConfig(sso_enabled)
        return real_get(name, *args, **kwargs)

    templar = Templar(loader=DataLoader(), variables={"application_id": APP})
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        rendered = templar.template(trust_as_template("\n".join(rows)))
    return dict(row.split("=", 1) for row in rendered.splitlines() if row)


class TestPlaywrightEnvPersonaBlocks(unittest.TestCase):
    def test_without_the_gate_both_signed_in_personas_are_blocked(self) -> None:
        self.assertEqual(
            dict.fromkeys(SIGNED_IN_PERSONAS, "true"),
            render_persona_flags(False),
            "the service reads the user only from the oauth2-proxy gate's "
            "headers and answers 401 without them, so an sso: false variant "
            "leaves the administrator and biber personas no sign-in path",
        )

    def test_behind_the_gate_both_signed_in_personas_run(self) -> None:
        self.assertEqual(
            dict.fromkeys(SIGNED_IN_PERSONAS, "false"),
            render_persona_flags(True),
            "with SSO enabled the gate signs both personas in, so blocking "
            "them would drop the only end-to-end proof of the auth chain",
        )


if __name__ == "__main__":
    unittest.main()
