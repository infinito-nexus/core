import unittest

from ansible.errors import AnsibleError

from plugins.lookup.unit_name import LookupModule


class DummyTemplar:
    def __init__(self, available_variables=None, rendered=None):
        self.available_variables = available_variables or {}
        self._rendered = rendered or {}

    def template(self, s: str, **kwargs):
        return self._rendered.get(s, s)


class UnitNameLookupTests(unittest.TestCase):
    def _mk_lookup(self, version_suffix=".2.0.0.infinito.nexus", rendered=None):
        lm = LookupModule()
        lm._templar = DummyTemplar(
            available_variables={"SYS_SERVICE_VERSION_SUFFIX": version_suffix},
            rendered=rendered,
        )
        lm.set_options = lambda *args, **kwargs: None
        return lm

    def test_default_suffix_service(self):
        res = self._mk_lookup().run(["svc-foo"])
        self.assertEqual(res, ["svc-foo.2.0.0.infinito.nexus.service"])

    def test_sys_ctl_prefix_is_removed(self):
        res = self._mk_lookup().run(["sys-ctl-cln-bkps"])
        self.assertEqual(res, ["cln-bkps.2.0.0.infinito.nexus.service"])

    def test_explicit_timer_suffix_with_dot(self):
        res = self._mk_lookup().run(["svc-foo"], suffix=".timer")
        self.assertEqual(res, ["svc-foo.2.0.0.infinito.nexus.timer"])

    def test_explicit_timer_suffix_without_dot(self):
        res = self._mk_lookup().run(["svc-foo"], suffix="timer")
        self.assertEqual(res, ["svc-foo.2.0.0.infinito.nexus.timer"])

    def test_suffix_false_means_no_suffix(self):
        res = self._mk_lookup().run(["svc-foo"], suffix=False)
        self.assertEqual(res, ["svc-foo.2.0.0.infinito.nexus"])

    def test_template_unit_id_endswith_at(self):
        res = self._mk_lookup().run(["alarm@"])
        self.assertEqual(res, ["alarm.2.0.0.infinito.nexus@.service"])

    def test_template_unit_id_endswith_at_with_sys_ctl_prefix(self):
        res = self._mk_lookup().run(["sys-ctl-alm-compose@"], suffix=False)
        self.assertEqual(res, ["alm-compose.2.0.0.infinito.nexus@"])

    def test_multiple_terms(self):
        res = self._mk_lookup().run(["a", "b"], suffix=".timer")
        self.assertEqual(
            res,
            [
                "a.2.0.0.infinito.nexus.timer",
                "b.2.0.0.infinito.nexus.timer",
            ],
        )

    def test_missing_terms_raises(self):
        with self.assertRaises(AnsibleError) as ctx:
            self._mk_lookup().run([])
        self.assertIn("at least one term", str(ctx.exception))

    def test_missing_version_suffix_raises(self):
        lm = LookupModule()
        lm._templar = DummyTemplar(available_variables={})
        lm.set_options = lambda *args, **kwargs: None
        with self.assertRaises(AnsibleError) as ctx:
            lm.run(["svc-foo"])
        self.assertIn("SYS_SERVICE_VERSION_SUFFIX is not defined", str(ctx.exception))

    def test_templated_version_suffix_is_rendered_and_lowered(self):
        template = ".{{ lookup('version') | lower }}.{{ SOFTWARE_DOMAIN }}"
        lm = self._mk_lookup(
            version_suffix=template,
            rendered={template: ".2.0.0.Infinito.Nexus"},
        )
        self.assertEqual(lm.run(["svc-foo"]), ["svc-foo.2.0.0.infinito.nexus.service"])

    def test_unresolved_version_suffix_template_raises(self):
        lm = self._mk_lookup(version_suffix="{{ UNKNOWN_VAR }}")
        with self.assertRaises(AnsibleError) as ctx:
            lm.run(["svc-foo"])
        self.assertIn(
            "unresolved template for 'SYS_SERVICE_VERSION_SUFFIX'", str(ctx.exception)
        )

    def test_malformed_version_suffix_raises(self):
        for malformed in ("2.0.0.infinito.nexus", "..infinito.nexus"):
            lm = self._mk_lookup(version_suffix=malformed)
            with self.assertRaises(AnsibleError) as ctx:
                lm.run(["svc-foo"])
            self.assertIn("must read '.<version>.<domain>'", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
