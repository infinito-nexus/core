# tests/unit/utils/test_templating.py
import os
import sys
import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError

from plugins.filter.ca_trust_paths import ca_cert_host

from . import PROJECT_ROOT

sys.path.insert(0, str(PROJECT_ROOT))

from utils.templating.ansible import (
    render_ansible_strict,
)


class _FakeTemplarLookupUndefined:
    """
    Simulates the earlier failure:
      - templar exists
      - but cannot evaluate lookup()
      - returns string unchanged => must trigger fallback evaluator
    """

    def __init__(self):
        self.available_variables = {}

    def template(self, s, *args, **kwargs):
        return s


class _FakeTemplarRejectsVariablesKwarg:
    """
    Simulates the earlier failure:
      Templar.template() got an unexpected keyword argument 'variables'
    We ensure our helper does NOT pass variables kwarg.
    """

    def __init__(self):
        self.available_variables = {}

    def template(self, s, fail_on_undefined=False):
        if s.strip() == "{{ CA_ROOT.cert_host }}":
            ca_root = self.available_variables.get("CA_ROOT", {})
            return ca_root.get("cert_host", s)
        return s


class TestTemplatingRenderStrict(unittest.TestCase):
    def test_plain_string_passthrough(self):
        out = render_ansible_strict(
            templar=None,
            raw="/etc/infinito/ca/root-ca.crt",
            var_name="x",
            err_prefix="t",
            variables={},
        )
        self.assertEqual(out, "/etc/infinito/ca/root-ca.crt")

    def test_none_hard_fails(self):
        with self.assertRaises(AnsibleError):
            render_ansible_strict(
                templar=None,
                raw=None,
                var_name="x",
                err_prefix="t",
                variables={},
            )

    def test_empty_after_render_hard_fails(self):
        with self.assertRaises(AnsibleError):
            render_ansible_strict(
                templar=None,
                raw="  ",
                var_name="x",
                err_prefix="t",
                variables={},
            )

    def test_env_lookup_fallback_when_lookup_undefined_like(self):
        with patch.dict(os.environ, {"domain": "infinito.localhost"}, clear=False):
            out = render_ansible_strict(
                templar=_FakeTemplarLookupUndefined(),
                raw="{{ lookup('env', 'domain') | default('infinito.localhost', true) }}",
                var_name="CA_TRUST.trust_name",
                err_prefix="compose_ca_inject_cmd",
                variables={},
            )
        self.assertEqual(out, "infinito.localhost")

    def test_env_lookup_default_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            out = render_ansible_strict(
                templar=_FakeTemplarLookupUndefined(),
                raw="{{ lookup('env', 'DOMAIN') | default('infinito.localhost', true) }}",
                var_name="CA_TRUST.trust_name",
                err_prefix="compose_ca_inject_cmd",
                variables={},
            )
        self.assertEqual(out, "infinito.localhost")

    def test_ca_root_nested_var_resolves_without_templar(self):
        #
        variables = {
            "SOFTWARE_DOMAIN": "infinito.nexus",
            "CA_ROOT": {
                "cert_host": "/etc/{{ SOFTWARE_DOMAIN }}/ca/root-ca.crt",
            },
        }
        out = render_ansible_strict(
            templar=None,
            raw="{{ CA_ROOT.cert_host }}",
            var_name="CA_TRUST.cert_host",
            err_prefix="compose_ca_inject_cmd",
            variables=variables,
        )
        self.assertEqual(out, ca_cert_host("infinito.nexus"))

    def test_templar_available_variables_is_used_no_variables_kwarg(self):
        #
        variables = {"CA_ROOT": {"cert_host": "/etc/infinito/ca/root-ca.crt"}}
        out = render_ansible_strict(
            templar=_FakeTemplarRejectsVariablesKwarg(),
            raw="{{ CA_ROOT.cert_host }}",
            var_name="CA_TRUST.cert_host",
            err_prefix="compose_ca_inject_cmd",
            variables=variables,
        )
        self.assertEqual(out, "/etc/infinito/ca/root-ca.crt")

    def test_templar_merges_variables_onto_available_variables(self):
        # Regression guard: prev available_variables (e.g. ansible_facts,
        # hostvars) must survive the call — caller-supplied variables are
        # layered on top, not substituted for the existing map.
        class _FakeTemplarRecordingAvail:
            def __init__(self, preset):
                self.available_variables = dict(preset)
                self.seen_on_call = None

            def template(self, s, fail_on_undefined=False):
                self.seen_on_call = dict(self.available_variables)
                if s.strip() == "{{ CA_ROOT.cert_host }}":
                    return self.available_variables.get("CA_ROOT", {}).get(
                        "cert_host", s
                    )
                if s.strip() == "{{ ANSIBLE_FACT }}":
                    return self.available_variables.get("ANSIBLE_FACT", s)
                return s

        preset = {"ANSIBLE_FACT": "from-prev-avail"}
        templar = _FakeTemplarRecordingAvail(preset)
        variables = {"CA_ROOT": {"cert_host": "/etc/infinito/ca/root-ca.crt"}}

        out = render_ansible_strict(
            templar=templar,
            raw="{{ CA_ROOT.cert_host }}",
            var_name="CA_TRUST.cert_host",
            err_prefix="t",
            variables=variables,
        )
        self.assertEqual(out, "/etc/infinito/ca/root-ca.crt")

        self.assertIn("ANSIBLE_FACT", templar.seen_on_call)
        self.assertEqual(templar.seen_on_call["ANSIBLE_FACT"], "from-prev-avail")
        self.assertIn("CA_ROOT", templar.seen_on_call)

        self.assertEqual(templar.available_variables, preset)

    def test_unresolved_jinja_hard_fails(self):
        with self.assertRaises(AnsibleError):
            render_ansible_strict(
                templar=_FakeTemplarLookupUndefined(),
                raw="{{ DOES_NOT_EXIST }}",
                var_name="x",
                err_prefix="t",
                variables={},
            )

    def test_multi_round_rendering(self):
        variables = {
            "SOFTWARE_DOMAIN": "infinito.nexus",
            "CA_ROOT": {"cert_host": "/etc/{{ SOFTWARE_DOMAIN }}/ca/root-ca.crt"},
        }
        out = render_ansible_strict(
            templar=_FakeTemplarLookupUndefined(),
            raw="{{ CA_ROOT.cert_host }}",
            var_name="x",
            err_prefix="t",
            variables=variables,
        )
        self.assertEqual(out, ca_cert_host("infinito.nexus"))

    def test_embedded_expression_in_string(self):
        variables = {"SOFTWARE_DOMAIN": "infinito.nexus"}
        out = render_ansible_strict(
            templar=None,
            raw="/etc/{{ SOFTWARE_DOMAIN }}/ca/root-ca.crt",
            var_name="x",
            err_prefix="t",
            variables=variables,
        )
        self.assertEqual(out, ca_cert_host("infinito.nexus"))

    def test_inline_conditional_with_concat(self):
        # Mirrors web-app-mailu/meta/server.yml (inline conditional + ~ concat).
        raw = (
            "{{ ('mail.' ~ DOMAIN_PRIMARY) if MAIL_PROVIDER == 'web-app-mailu' "
            "else ('legacy-mail.' ~ DOMAIN_PRIMARY) }}"
        )
        base = {"DOMAIN_PRIMARY": "example.com"}
        self.assertEqual(
            render_ansible_strict(
                templar=None,
                raw=raw,
                var_name="x",
                err_prefix="t",
                variables={**base, "MAIL_PROVIDER": "web-app-mailu"},
            ),
            "mail.example.com",
        )
        self.assertEqual(
            render_ansible_strict(
                templar=None,
                raw=raw,
                var_name="x",
                err_prefix="t",
                variables={**base, "MAIL_PROVIDER": "web-app-stalwart"},
            ),
            "legacy-mail.example.com",
        )
        # Unset MAIL_PROVIDER takes the else branch.
        self.assertEqual(
            render_ansible_strict(
                templar=None,
                raw=raw,
                var_name="x",
                err_prefix="t",
                variables=base,
            ),
            "legacy-mail.example.com",
        )

    def test_filters_lower_upper_default(self):
        variables = {"NAME": "MiXeD", "EMPTY": ""}
        out1 = render_ansible_strict(
            templar=None,
            raw="{{ NAME | lower }}",
            var_name="x",
            err_prefix="t",
            variables=variables,
        )
        self.assertEqual(out1, "mixed")

        out2 = render_ansible_strict(
            templar=None,
            raw="{{ NAME | upper }}",
            var_name="x",
            err_prefix="t",
            variables=variables,
        )
        self.assertEqual(out2, "MIXED")

        out3 = render_ansible_strict(
            templar=None,
            raw="{{ EMPTY | default('fallback', true) }}",
            var_name="x",
            err_prefix="t",
            variables=variables,
        )
        self.assertEqual(out3, "fallback")


if __name__ == "__main__":
    unittest.main()
