"""Unit tests for ``plugins/lookup/mcp_client_login.py``.

The sub-lookups are stubbed so the tests stay hermetic: what matters is that
the login a client presents is the principal's ``username`` rather than the
users-dict key, and that an owner the users dict never declared still yields a
name instead of an empty basic-auth user.

The stub is installed on ``mcp_client_bearer``, because that module owns the
shared ``resolve_provider_credential`` both client lookups resolve through.
"""

from __future__ import annotations

import importlib
import unittest
from unittest.mock import MagicMock, patch

from ansible.errors import AnsibleError

bearer_module = importlib.import_module("plugins.lookup.mcp_client_bearer")
login_module = importlib.import_module("plugins.lookup.mcp_client_login")


class _DummyTemplar:
    def __init__(self):
        self.available_variables = {}


class TestMcpClientLoginLookup(unittest.TestCase):
    def _run(self, terms, credential, role_credentials=None, users=None):
        lookup = login_module.LookupModule()
        lookup._templar = _DummyTemplar()
        lookup._loader = MagicMock()

        class _StubConfig:
            def run(self, terms_, variables=None, **kwargs):
                if terms_[1] == "mcp.credential":
                    return [credential]
                return [role_credentials if role_credentials is not None else {}]

        class _StubUsers:
            def run(self, terms_, variables=None, **kwargs):
                return [users if users is not None else {}]

        def _dispatch(name, **_kwargs):
            return _StubConfig() if name == "config" else _StubUsers()

        with patch.object(bearer_module, "lookup_loader") as loader:
            loader.get.side_effect = _dispatch
            return lookup.run(terms, variables={})

    def test_a_shortened_account_answers_with_its_username(self):
        credential = {
            "owner": "mcp-web-app-wordpress",
            "source": "token_store",
            "key": "web-app-wordpress",
        }
        self.assertEqual(
            ["mcp-wordpress"],
            self._run(
                ["web-app-wordpress"],
                credential,
                users={
                    "username": "mcp-wordpress",
                    "tokens": {"web-app-wordpress": "pw"},
                },
            ),
        )

    def test_an_owner_the_users_dict_never_declared_falls_back_to_the_key(self):
        credential = {
            "owner": "mcp-web-app-prometheus",
            "source": "credentials",
            "key": "mcp_bearer",
        }
        self.assertEqual(
            ["mcp-web-app-prometheus"],
            self._run(
                ["web-app-prometheus"],
                credential,
                role_credentials={"mcp_bearer": "adapter-secret"},
            ),
        )

    def test_the_login_and_the_bearer_resolve_through_one_function(self):
        """A second resolver would let the two drift onto different principals."""
        self.assertIs(
            login_module.resolve_provider_credential,
            bearer_module.resolve_provider_credential,
        )

    def test_an_undeclared_credential_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["web-app-wordpress"], None)

    def test_a_missing_application_id_raises(self):
        with self.assertRaises(AnsibleError):
            self._run([], {})


if __name__ == "__main__":
    unittest.main()
