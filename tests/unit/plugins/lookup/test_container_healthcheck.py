"""Unit tests for the container_healthcheck lookup plugin.

Pins that values taken straight out of the play vars are templated before
use. ``include_role: vars:`` hands them over unrendered, so under
``sys-stk-full`` ``application_id`` arrives as the literal string
``{{ sys_stk_full_application_id }}`` and ``container_hostname`` as
``{{ lookup('domain', application_id) }}``.
"""

from __future__ import annotations

import importlib.util
import unittest

from ansible.errors import AnsibleError

from . import PROJECT_ROOT

SERVICES = {
    "web-app-dashboard": {
        "services.dashboard.healthcheck": {"flavor": "tcp", "start_period": "10m"},
        "services.dashboard.ports.internal.http": 5000,
    },
    "web-app-x": {
        "services.web.healthcheck": {"flavor": "curl", "samples": 2},
        "services.web.ports.internal.http": 8080,
    },
    "web-app-bare": {},
}


def _load_lookup():
    spec = importlib.util.spec_from_file_location(
        "lookup_container_healthcheck",
        str(PROJECT_ROOT / "plugins/lookup/container_healthcheck.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class _DummyTemplar:
    def __init__(self, available_variables=None, rendered=None):
        self.available_variables = available_variables or {}
        self.rendered = rendered or {}

    def template(self, value):
        return self.rendered[value]


class _DummyConfigLookup:
    def run(self, terms, variables=None):
        application_id, path, default = terms[0], terms[1], terms[2]
        return [SERVICES.get(application_id, {}).get(path, default)]


class TestContainerHealthcheckLookup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_lookup()

    def setUp(self):
        self.original_loader = self.mod.lookup_loader
        self.mod.lookup_loader = type(
            "_Loader", (), {"get": staticmethod(lambda *a, **kw: _DummyConfigLookup())}
        )()

    def tearDown(self):
        self.mod.lookup_loader = self.original_loader

    def _make(self, variables, rendered=None):
        lm = self.mod.LookupModule()
        lm._templar = _DummyTemplar(variables, rendered)
        lm._loader = None
        return lm

    def test_unrendered_application_id_is_templated(self):
        vars_ = {
            "application_id": "{{ sys_stk_full_application_id }}",
            "sys_stk_full_application_id": "web-app-dashboard",
        }
        rendered = {"{{ sys_stk_full_application_id }}": "web-app-dashboard"}
        block = self._make(vars_, rendered).run(["dashboard"], variables=vars_)[0]
        self.assertIn("/dev/tcp/localhost/5000", block)
        self.assertIn("start_period: 10m", block)

    def test_unrendered_container_hostname_is_templated(self):
        vars_ = {
            "application_id": "web-app-x",
            "container_hostname": "{{ lookup('domain', application_id) }}",
        }
        rendered = {"{{ lookup('domain', application_id) }}": "x.example.com"}
        block = self._make(vars_, rendered).run(["web"], variables=vars_)[0]
        self.assertIn("Host: x.example.com", block)
        self.assertNotIn("lookup(", block)

    def test_plain_application_id_passes_through(self):
        vars_ = {"application_id": "web-app-dashboard"}
        block = self._make(vars_).run(["dashboard"], variables=vars_)[0]
        self.assertIn("/dev/tcp/localhost/5000", block)

    def test_missing_flavor_and_test_raises(self):
        vars_ = {"application_id": "web-app-bare"}
        with self.assertRaises(AnsibleError) as ctx:
            self._make(vars_).run(["bare"], variables=vars_)
        self.assertIn("web-app-bare", str(ctx.exception))

    def test_missing_application_id_raises(self):
        with self.assertRaises(AnsibleError):
            self._make({}).run(["web"], variables={})

    def test_missing_service_name_raises(self):
        with self.assertRaises(AnsibleError):
            self._make({}).run([], variables={})

    def test_unrendered_leftover_template_raises(self):
        vars_ = {"application_id": "{{ untrusted }}"}
        rendered = {"{{ untrusted }}": "{{ untrusted }}"}
        with self.assertRaises(AnsibleError) as ctx:
            self._make(vars_, rendered).run(["web"], variables=vars_)
        self.assertIn("did not render", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
