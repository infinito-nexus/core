"""The OIDC addon must not be on when Nextcloud has no SSO provider.

``meta/addons/oidc_login.yml`` gates on ``lookup('sso_oidc_plugin')``, which the
applications render evaluates while it is still in flight. Under that re-entry
guard the merged view hands out service flags as their own Jinja text, and
``bool("{{ ... }}")`` is True: the lookup read ``services.ldap.enabled`` as
enabled on a deployment that has neither Keycloak nor OpenLDAP and announced
``oidc_login``. Nextcloud then advertised a login hand-off to a provider that is
not deployed, while ``templates/config/oidc.config.php.j2`` re-read the same
setting at task time and correctly wrote nothing.

The stubbed lookup tests next to the plugin cannot see this: a stub resolves the
path but does not render it. This renders for real.
"""

from __future__ import annotations

import unittest

from utils.cache import _reset_cache_for_tests
from utils.cache.applications import get_merged_applications


def _templar(variables: dict):
    from ansible.parsing.dataloader import DataLoader
    from ansible.template import Templar

    templar = Templar(loader=DataLoader(), variables=dict(variables))
    templar.available_variables = dict(variables)
    return templar


def _addon_flags(*deployed: str) -> dict:
    variables = {"group_names": list(deployed), "applications": {}}
    _reset_cache_for_tests()
    try:
        applications = get_merged_applications(
            variables=variables, templar=_templar(variables)
        )
    finally:
        _reset_cache_for_tests()
    nextcloud = applications["web-app-nextcloud"]
    addons = nextcloud.get("addons") or {}
    services = nextcloud.get("services") or {}
    return {
        "sso": (services.get("sso") or {}).get("enabled"),
        "ldap": (services.get("ldap") or {}).get("enabled"),
        **{
            name: (addons.get(name) or {}).get("enabled")
            for name in ("oidc_login", "user_oidc", "sociallogin")
        },
    }


class TestOidcAddonFollowsSso(unittest.TestCase):
    def test_no_provider_means_no_oidc_addon(self) -> None:
        flags = _addon_flags("web-app-nextcloud")

        self.assertEqual(flags["sso"], False)
        self.assertEqual(
            (flags["oidc_login"], flags["user_oidc"], flags["sociallogin"]),
            (False, False, False),
            "no OIDC plugin may be announced without an SSO provider",
        )


if __name__ == "__main__":
    unittest.main()
