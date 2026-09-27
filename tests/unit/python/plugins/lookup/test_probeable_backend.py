from __future__ import annotations

import unittest
from unittest import mock
from unittest.mock import patch

from ansible.plugins.loader import lookup_loader

from . import PROJECT_ROOT  # noqa: F401


class _DummyTemplar:
    def __init__(self, available_vars: dict):
        self.available_variables = available_vars


class ProbeableBackendTests(unittest.TestCase):
    def setUp(self) -> None:
        self.lookup = lookup_loader.get("probeable_backend")
        self.lookup._templar = _DummyTemplar({})
        self.lookup._loader = mock.MagicMock()

    def _run(self, terms, applications: dict, **vars_):
        class _StubApplications:
            def run(self, terms_, variables=None, **kw):
                return [applications]

        with patch.object(lookup_loader, "get", return_value=_StubApplications()):
            return self.lookup.run(terms, variables=vars_)

    def test_a_role_without_any_port_has_nothing_to_probe(self) -> None:
        apps = {"web-svc-mirror": {"services": {"mirror": {}}}}

        self.assertEqual(self._run(["web-svc-mirror"], apps), [False])

    def test_a_local_port_is_probeable(self) -> None:
        apps = {
            "web-app-foo": {"services": {"foo": {"ports": {"local": {"http": 8080}}}}}
        }

        self.assertEqual(self._run(["web-app-foo"], apps), [True])

    def test_an_internal_port_alone_is_probeable(self) -> None:
        apps = {
            "web-app-foo": {
                "services": {"foo": {"ports": {"internal": {"http": 8008}}}}
            }
        }

        self.assertEqual(
            self._run(["web-app-foo"], apps),
            [True],
            "swarm resolves the upstream from the internal port, so a role "
            "carrying only that one still has a backend to probe",
        )

    def test_a_port_the_role_resolved_itself_counts(self) -> None:
        apps = {"web-app-foo": {"services": {"foo": {}}}}

        self.assertEqual(self._run(["web-app-foo"], apps, http_port="8021"), [True])


if __name__ == "__main__":
    unittest.main()
