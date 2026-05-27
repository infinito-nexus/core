#
# Unit tests for plugins/lookup/unit_name.py using Python's built-in unittest.
#
# Run with:
#   python -m unittest -v
#
# Notes:
# - These tests do NOT require a full Ansible runtime; we mock the templar.
# - They validate the naming format and error handling.

import unittest

from ansible.errors import AnsibleError

# Import your lookup plugin (adjust import path if your repo layout differs)
from plugins.lookup.unit_name import LookupModule


class DummyTemplar:
    """Minimal templar stub to satisfy the lookup plugin."""

    def __init__(self, available_variables=None, version="1.2.3"):
        self.available_variables = available_variables or {}
        self._version = version

    def template(self, s: str, **kwargs):
        # The plugin calls: self._templar.template("{{ lookup('version') }}")
        if "lookup('version')" in s:
            return self._version
        if "{{ SOFTWARE_NAME | lower }}" in s:
            return str(self.available_variables.get("SOFTWARE_NAME", "")).lower()
        return s


class UnitNameLookupTests(unittest.TestCase):
    def _mk_lookup(
        self, software_domain="infinito.nexus", version="1.2.3"
    ) -> LookupModule:
        lm = LookupModule()

        # Inject a dummy templar with variables
        lm._templar = DummyTemplar(
            available_variables={"SOFTWARE_DOMAIN": software_domain},
            version=version,
        )

        # The plugin calls set_options(); for unit tests we make it a no-op
        lm.set_options = lambda *args, **kwargs: None

        return lm

    def test_default_suffix_service(self):
        lm = self._mk_lookup(software_domain="Infinito.Nexus", version="2.0.0")
        res = lm.run(["svc-foo"])
        self.assertEqual(res, ["svc-foo.2.0.0.infinito.nexus.service"])

    def test_sys_ctl_prefix_is_removed(self):
        lm = self._mk_lookup(software_domain="Infinito.Nexus", version="2.0.0")
        res = lm.run(["sys-ctl-cln-bkps"])
        self.assertEqual(res, ["cln-bkps.2.0.0.infinito.nexus.service"])

    def test_explicit_timer_suffix_with_dot(self):
        lm = self._mk_lookup(software_domain="infinito.nexus", version="2.0.0")
        res = lm.run(["svc-foo"], suffix=".timer")
        self.assertEqual(res, ["svc-foo.2.0.0.infinito.nexus.timer"])

    def test_explicit_timer_suffix_without_dot(self):
        lm = self._mk_lookup(software_domain="infinito.nexus", version="2.0.0")
        res = lm.run(["svc-foo"], suffix="timer")
        self.assertEqual(res, ["svc-foo.2.0.0.infinito.nexus.timer"])

    def test_suffix_false_means_no_suffix(self):
        lm = self._mk_lookup(software_domain="infinito.nexus", version="2.0.0")
        res = lm.run(["svc-foo"], suffix=False)
        self.assertEqual(res, ["svc-foo.2.0.0.infinito.nexus"])

    def test_template_unit_id_endswith_at(self):
        lm = self._mk_lookup(software_domain="infinito.nexus", version="2.0.0")
        res = lm.run(["alarm@"])
        # Template semantics: "<base>.<ver>.<sw>@.service"
        self.assertEqual(res, ["alarm.2.0.0.infinito.nexus@.service"])

    def test_template_unit_id_endswith_at_with_sys_ctl_prefix(self):
        lm = self._mk_lookup(software_domain="infinito.nexus", version="2.0.0")
        res = lm.run(["sys-ctl-alm-compose@"], suffix=False)
        self.assertEqual(res, ["alm-compose.2.0.0.infinito.nexus@"])

    def test_multiple_terms(self):
        lm = self._mk_lookup(software_domain="infinito.nexus", version="2.0.0")
        res = lm.run(["a", "b"], suffix=".timer")
        self.assertEqual(
            res,
            [
                "a.2.0.0.infinito.nexus.timer",
                "b.2.0.0.infinito.nexus.timer",
            ],
        )

    def test_missing_terms_raises(self):
        lm = self._mk_lookup()
        with self.assertRaises(AnsibleError) as ctx:
            lm.run([])
        self.assertIn("at least one term", str(ctx.exception))

    def test_missing_software_name_raises(self):
        lm = LookupModule()
        lm._templar = DummyTemplar(available_variables={}, version="1.2.3")
        lm.set_options = lambda *args, **kwargs: None

        with self.assertRaises(AnsibleError) as ctx:
            lm.run(["svc-foo"])
        self.assertIn("SOFTWARE_DOMAIN is not defined", str(ctx.exception))

    def test_empty_version_raises(self):
        lm = self._mk_lookup(software_domain="infinito.nexus", version="   ")
        with self.assertRaises(AnsibleError) as ctx:
            lm.run(["svc-foo"])
        self.assertIn("lookup('version') returned an empty value", str(ctx.exception))

    def test_templated_software_domain_is_rendered(self):
        lm = LookupModule()
        lm._templar = DummyTemplar(
            available_variables={
                "SOFTWARE_DOMAIN": "{{ SOFTWARE_NAME | lower }}",
                "SOFTWARE_NAME": "Infinito.Nexus",
            },
            version="2.0.0",
        )
        lm.set_options = lambda *args, **kwargs: None

        res = lm.run(["svc-foo"])
        self.assertEqual(res, ["svc-foo.2.0.0.infinito.nexus.service"])

    def test_unresolved_software_domain_template_raises(self):
        lm = LookupModule()
        lm._templar = DummyTemplar(
            available_variables={"SOFTWARE_DOMAIN": "{{ UNKNOWN_VAR | lower }}"},
            version="2.0.0",
        )
        lm.set_options = lambda *args, **kwargs: None

        with self.assertRaises(AnsibleError) as ctx:
            lm.run(["svc-foo"])
        self.assertIn("unresolved template for 'SOFTWARE_DOMAIN'", str(ctx.exception))

    def test_version_fallback_direct_lookup_plugin(self):
        lm = self._mk_lookup(
            software_domain="infinito.nexus", version="{{ lookup('version') }}"
        )
        res = lm.run(["svc-foo"])

        self.assertRegex(
            res[0],
            r"^svc-foo\.[0-9A-Za-z._+-]+\.infinito\.nexus\.service$",
        )


if __name__ == "__main__":
    unittest.main()
