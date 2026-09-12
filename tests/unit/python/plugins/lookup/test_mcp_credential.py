"""Unit tests for ``plugins/lookup/mcp_credential.py``.

The sub-lookups are stubbed so the tests stay hermetic: what matters is that
one call site cannot resolve the owner, the token key or the fallbacks
differently from another.
"""

from __future__ import annotations

import importlib.util
import unittest
from unittest import mock
from unittest.mock import patch

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module():
    path = PROJECT_ROOT / "plugins/lookup/mcp_credential.py"
    spec = importlib.util.spec_from_file_location("lookup_mcp_credential", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _DummyTemplar:
    def __init__(self):
        self.available_variables = {}


class TestMcpCredentialLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def _run(self, terms, owner="mcp-web-app-gitea", users=None):
        lookup = self.mod.LookupModule()
        lookup._templar = _DummyTemplar()
        lookup._loader = mock.MagicMock()

        class _StubConfig:
            def run(self, terms_, variables=None, **kwargs):
                return [owner]

        class _StubUsers:
            def run(self, terms_, variables=None, **kwargs):
                return [users if users is not None else {}]

        def _dispatch(name, **_kwargs):
            return _StubConfig() if name == "config" else _StubUsers()

        with patch.object(self.mod.lookup_loader, "get", side_effect=_dispatch):
            return lookup.run(terms, variables={})

    def test_the_stored_token_is_returned_trimmed(self):
        users = {"tokens": {"web-app-gitea": "  tok-123  "}}
        self.assertEqual(["tok-123"], self._run(["web-app-gitea"], users=users))

    def test_a_provider_without_a_token_yet_reads_empty(self):
        self.assertEqual([""], self._run(["web-app-gitea"], users={"tokens": {}}))

    def test_another_providers_token_is_not_returned(self):
        users = {"tokens": {"web-app-gitlab": "tok-other"}}
        self.assertEqual([""], self._run(["web-app-gitea"], users=users))

    def test_a_missing_owner_declaration_raises(self):
        with self.assertRaises(AnsibleError):
            self._run(["web-app-gitea"], owner="")

    def test_zero_or_too_many_terms_raise(self):
        for terms in ([], ["a", "b", "c"], ["   "]):
            with self.assertRaises(AnsibleError):
                self._run(terms)

    def test_an_unknown_role_raises_instead_of_returning_nothing(self):
        with self.assertRaises(AnsibleError):
            self._run(["web-app-gitea", "mcp-writter"])

    def test_a_writer_token_is_read_from_its_own_key(self):
        self.assertEqual(
            ["w-tok"],
            self._run(
                ["web-app-gitea", "mcp-writer"],
                users={"tokens": {"web-app-gitea:mcp-writer": "w-tok"}},
            ),
        )

    def test_a_role_reads_a_separate_token(self):
        self.assertEqual(
            [""],
            self._run(
                ["web-app-gitea", "mcp-writer"],
                users={"tokens": {"web-app-gitea": "reader-only"}},
            ),
        )


if __name__ == "__main__":
    unittest.main()
