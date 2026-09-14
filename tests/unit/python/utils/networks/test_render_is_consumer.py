from __future__ import annotations

import unittest
from typing import ClassVar

from utils.networks.render import _is_consumer

from ._render_helpers import _const_lookup_config, _const_lookup_database


class TestIsConsumer(unittest.TestCase):
    def test_database_kind_all_conditions(self):
        entry = {
            "role": "svc-db-postgres",
            "overlay": {"consumer": {"kind": "database"}},
        }
        lookup_db = _const_lookup_database(
            enabled=True, shared=True, id="svc-db-postgres"
        )
        self.assertTrue(
            _is_consumer(entry, "web-app-baserow", _const_lookup_config(), lookup_db)
        )

    def test_database_kind_wrong_provider(self):
        entry = {
            "role": "svc-db-mariadb",
            "overlay": {"consumer": {"kind": "database"}},
        }
        lookup_db = _const_lookup_database(
            enabled=True, shared=True, id="svc-db-postgres"
        )
        self.assertFalse(
            _is_consumer(entry, "web-app-baserow", _const_lookup_config(), lookup_db)
        )

    def test_database_kind_not_shared(self):
        entry = {
            "role": "svc-db-mariadb",
            "overlay": {"consumer": {"kind": "database"}},
        }
        lookup_db = _const_lookup_database(
            enabled=True, shared=False, id="svc-db-mariadb"
        )
        self.assertFalse(
            _is_consumer(entry, "web-app-baserow", _const_lookup_config(), lookup_db)
        )

    def test_services_flags_explicit_key_and_flags(self):
        entry = {
            "role": "svc-prx-openresty",
            "entity_name": "openresty",
            "overlay": {
                "consumer": {
                    "kind": "services_flags",
                    "key": "sso",
                    "flags": ["enabled"],
                }
            },
        }
        cfg = _const_lookup_config(**{"services.sso.enabled": True})
        self.assertTrue(
            _is_consumer(entry, "web-app-baserow", cfg, _const_lookup_database())
        )

    def test_services_flags_default_key_from_provides(self):
        entry = {
            "role": "svc-db-openldap",
            "entity_name": "openldap",
            "provides": "ldap",
            "overlay": {},
        }
        cfg = _const_lookup_config(
            **{"services.ldap.enabled": True, "services.ldap.shared": True}
        )
        self.assertTrue(
            _is_consumer(entry, "web-app-bookwyrm", cfg, _const_lookup_database())
        )

    def test_services_flags_default_key_from_entity_name(self):
        entry = {
            "role": "svc-ai-ollama",
            "entity_name": "ollama",
            "overlay": {},
        }
        cfg = _const_lookup_config(
            **{"services.ollama.enabled": True, "services.ollama.shared": True}
        )
        self.assertTrue(
            _is_consumer(entry, "web-app-openwebui", cfg, _const_lookup_database())
        )

    def test_services_flags_default_flags_require_enabled_and_shared(self):
        entry = {
            "role": "svc-db-openldap",
            "entity_name": "openldap",
            "provides": "ldap",
            "overlay": {},
        }
        cfg = _const_lookup_config(**{"services.ldap.enabled": True})
        self.assertFalse(
            _is_consumer(entry, "web-app-x", cfg, _const_lookup_database())
        )

    def test_unknown_kind_returns_false(self):
        entry = {"role": "x", "overlay": {"consumer": {"kind": "future_thing"}}}
        self.assertFalse(
            _is_consumer(
                entry, "web-app-x", _const_lookup_config(), _const_lookup_database()
            )
        )

    def test_web_facing_matches_web_app_and_web_svc(self):
        entry = {
            "role": "svc-prx-openresty",
            "overlay": {"consumer": {"kind": "web_facing"}},
        }
        for app in ("web-app-baserow", "web-svc-logout"):
            self.assertTrue(
                _is_consumer(
                    entry, app, _const_lookup_config(), _const_lookup_database()
                ),
                msg=app,
            )

    def test_web_facing_rejects_non_web_roles(self):
        entry = {
            "role": "svc-prx-openresty",
            "overlay": {"consumer": {"kind": "web_facing"}},
        }
        for app in ("svc-db-mariadb", "svc-ai-ollama", "sys-svc-x"):
            self.assertFalse(
                _is_consumer(
                    entry, app, _const_lookup_config(), _const_lookup_database()
                ),
                msg=app,
            )


class TestIsConsumerOnionSso(unittest.TestCase):
    ENTRY: ClassVar[dict] = {
        "role": "svc-net-tor",
        "overlay": {
            "consumer": {
                "kind": "onion_sso",
                "key": "sso",
                "provider": "web-app-keycloak",
                "provider_key": "tor",
            }
        },
    }

    @staticmethod
    def _lookup(*, sso, provider_tor):
        def _inner(app, path, default):
            if app == "web-app-keycloak" and path == "services.tor.enabled":
                return provider_tor
            if path == "services.sso.enabled":
                return sso
            return default

        return _inner

    def _consumer(self, *, sso, provider_tor, entry=None):
        return _is_consumer(
            entry or self.ENTRY,
            "web-app-nextcloud",
            self._lookup(sso=sso, provider_tor=provider_tor),
            _const_lookup_database(),
        )

    def test_attaches_only_when_sso_consumer_meets_onion_provider(self):
        cases = [
            (True, True, True),
            (True, False, False),
            (False, True, False),
            (False, False, False),
        ]
        for sso, provider_tor, expected in cases:
            with self.subTest(sso=sso, provider_tor=provider_tor):
                self.assertIs(
                    self._consumer(sso=sso, provider_tor=provider_tor), expected
                )

    def test_provider_is_mandatory(self):
        entry = {"role": "svc-net-tor", "overlay": {"consumer": {"kind": "onion_sso"}}}
        self.assertFalse(self._consumer(sso=True, provider_tor=True, entry=entry))

    def test_provider_key_defaults_to_tor(self):
        entry = {
            "role": "svc-net-tor",
            "overlay": {
                "consumer": {"kind": "onion_sso", "provider": "web-app-keycloak"}
            },
        }
        self.assertTrue(self._consumer(sso=True, provider_tor=True, entry=entry))
        self.assertFalse(self._consumer(sso=True, provider_tor=False, entry=entry))


if __name__ == "__main__":
    unittest.main()
