"""Unit tests for ``plugins/lookup/mcp_client_bearer.py``.

The sub-lookups are stubbed so the tests stay hermetic: what matters is that
the source declared in ``mcp.credential`` decides which secret comes back, and
that a provider fronted by an adapter never answers with the token its upstream
principal holds.
"""

from __future__ import annotations

import importlib.util
import unittest
from unittest import mock
from unittest.mock import patch

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module():
    path = PROJECT_ROOT / "plugins/lookup/mcp_client_bearer.py"
    spec = importlib.util.spec_from_file_location("lookup_mcp_client_bearer", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _DummyTemplar:
    def __init__(self):
        self.available_variables = {}


class TestMcpClientBearerLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def _run(self, terms, credential, role_credentials=None, users=None):
        lookup = self.mod.LookupModule()
        lookup._templar = _DummyTemplar()
        lookup._loader = mock.MagicMock()

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

        with patch.object(self.mod.lookup_loader, "get", side_effect=_dispatch):
            return lookup.run(terms, variables={})

    def test_an_adapter_answers_with_its_own_rendered_bearer(self):
        credential = {
            "owner": "mcp-web-app-gitea",
            "source": "credentials",
            "key": "mcp_bearer",
        }
        self.assertEqual(
            ["adapter-secret"],
            self._run(
                ["web-app-gitea"],
                credential,
                role_credentials={"mcp_bearer": "adapter-secret"},
                users={"tokens": {"web-app-gitea": "upstream-pat"}},
            ),
        )

    def test_a_native_provider_answers_with_the_stored_token(self):
        credential = {
            "owner": "mcp-web-app-nextcloud",
            "source": "token_store",
            "key": "web-app-nextcloud",
        }
        self.assertEqual(
            ["stored-token"],
            self._run(
                ["web-app-nextcloud"],
                credential,
                users={"tokens": {"web-app-nextcloud": "stored-token"}},
            ),
        )

    def test_a_provider_without_a_secret_yet_reads_empty(self):
        credential = {
            "owner": "mcp-web-app-gitea",
            "source": "credentials",
            "key": "mcp_bearer",
        }
        self.assertEqual([""], self._run(["web-app-gitea"], credential))

    def test_an_undeclared_credential_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["web-app-gitea"], None)

    def test_a_missing_application_id_raises(self):
        with self.assertRaises(AnsibleError):
            self._run([], {})


if __name__ == "__main__":
    unittest.main()
