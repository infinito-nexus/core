# tests/unit/python/utils/test_jinja_strict.py
#
# Unit tests for utils/templating/jinja.py
#
# Focus:
# - strict Jinja2 rendering
# - recursive multi-pass expansion (nested Jinja)
# - hard-fail when unresolved markers remain or vars missing
# - hostvars overlay semantics

import unittest

from ansible.errors import AnsibleError

from utils.templating.jinja import (
    build_render_context,
    looks_like_jinja,
    render_jinja2_strict_recursive,
    render_strict,
)


class TestJinjaStrict(unittest.TestCase):
    def test_looks_like_jinja(self):
        self.assertFalse(looks_like_jinja("plain"))
        self.assertTrue(looks_like_jinja("{{ X }}"))
        self.assertTrue(looks_like_jinja("{% if x %}y{% endif %}"))

    def test_build_render_context_prefers_hostvars_overlay(self):
        variables = {
            "inventory_hostname": "host1",
            "SOFTWARE_NAME": "Outer",
            "hostvars": {
                "host1": {
                    "SOFTWARE_NAME": "Inner",
                    "EXTRA": "value",
                }
            },
        }
        ctx, inv_host = build_render_context(variables)
        self.assertEqual(inv_host, "host1")
        self.assertEqual(ctx["SOFTWARE_NAME"], "Inner")
        self.assertEqual(ctx["EXTRA"], "value")

    def test_render_strict_returns_raw_when_no_markers(self):
        variables = {"inventory_hostname": "localhost"}
        self.assertEqual(
            render_strict(
                "/etc/ssl/cert.pem",
                variables=variables,
                var_name="x",
                err_prefix="t",
            ),
            "/etc/ssl/cert.pem",
        )

    def test_render_strict_single_pass_success(self):
        variables = {
            "inventory_hostname": "localhost",
            "SOFTWARE_DOMAIN": "infinito",
        }
        out = render_strict(
            "/etc/{{ SOFTWARE_DOMAIN }}/ca/root-ca.crt",
            variables=variables,
            var_name="CA_ROOT.cert_host",
            err_prefix="t",
        )
        self.assertEqual(out, "/etc/infinito/ca/root-ca.crt")

    def test_render_strict_recursive_nested_vars_success(self):
        variables = {
            "inventory_hostname": "localhost",
            "SOFTWARE_DOMAIN": "infinito",
            "CA_ROOT": {"cert_host": "/etc/{{ SOFTWARE_DOMAIN }}/ca/root-ca.crt"},
            "CA_TRUST": {"cert_host": "{{ CA_ROOT.cert_host }}"},
        }
        out = render_strict(
            variables["CA_TRUST"]["cert_host"],
            variables=variables,
            var_name="CA_TRUST.cert_host",
            err_prefix="compose_ca_inject_cmd",
        )
        self.assertEqual(out, "/etc/infinito/ca/root-ca.crt")

    def test_render_jinja2_strict_recursive_fails_on_missing_var(self):
        variables = {"inventory_hostname": "localhost"}
        ctx, inv_host = build_render_context(variables)

        with self.assertRaises(AnsibleError):
            render_jinja2_strict_recursive(
                "/etc/{{ DOES_NOT_EXIST }}/x",
                ctx=ctx,
                inv_host=inv_host,
                var_name="missing",
                err_prefix="t",
                max_passes=3,
            )

    def test_render_strict_fails_when_markers_remain_after_stabilization(self):
        variables = {
            "inventory_hostname": "localhost",
            "A": "{{ B }}",
        }
        with self.assertRaises(AnsibleError):
            render_strict(
                "{{ A }}",
                variables=variables,
                var_name="test",
                err_prefix="t",
                max_passes=5,
            )

    def test_render_strict_fails_when_markers_remain_after_max_passes(self):
        variables = {"inventory_hostname": "localhost"}
        chain_len = 8
        for i in range(chain_len):
            k = chr(ord("A") + i)
            nxt = chr(ord("A") + i + 1) if i < chain_len - 1 else "FINAL"
            variables[k] = "{{ " + nxt + " }}"
        variables["FINAL"] = "ok"

        with self.assertRaises(AnsibleError):
            render_strict(
                "{{ A }}",
                variables=variables,
                var_name="chain",
                err_prefix="t",
                max_passes=3,
            )

        ok = render_strict(
            "{{ A }}",
            variables=variables,
            var_name="chain",
            err_prefix="t",
            max_passes=20,
        )
        self.assertEqual(ok, "ok")


if __name__ == "__main__":
    unittest.main()
