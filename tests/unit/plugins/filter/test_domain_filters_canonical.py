import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.canonical_domains_map import FilterModule


class TestDomainFilters(unittest.TestCase):
    def setUp(self):
        self.filter_module = FilterModule()
        # Sample primary domain
        self.primary = "example.com"

    def test_canonical_empty_apps(self):
        apps = {}
        expected = {}
        result = self.filter_module.canonical_domains_map(apps, self.primary)
        self.assertEqual(result, expected)

    def test_canonical_without_domains(self):
        apps = {"web-app-app1": {}}
        expected = {"web-app-app1": ["app1.example.com"]}
        result = self.filter_module.canonical_domains_map(apps, self.primary)
        self.assertEqual(result, expected)

    def test_canonical_with_list(self):
        apps = {"web-app-app1": {"domains": {"canonical": ["foo.com", "bar.com"]}}}
        result = self.filter_module.canonical_domains_map(apps, self.primary)
        self.assertCountEqual(result["web-app-app1"], ["foo.com", "bar.com"])

    def test_canonical_with_dict(self):
        apps = {
            "web-app-app1": {
                "domains": {"canonical": {"one": "one.com", "two": "two.com"}}
            }
        }
        result = self.filter_module.canonical_domains_map(apps, self.primary)
        self.assertEqual(result["web-app-app1"], {"one": "one.com", "two": "two.com"})

    def test_canonical_duplicate_raises(self):
        apps = {
            "web-app-app1": {
                "domains": {"canonical": ["dup.com"]},
            },
            "web-app-app2": {
                "domains": {"canonical": ["dup.com"]},
            },
        }
        with self.assertRaises(AnsibleFilterError) as cm:
            self.filter_module.canonical_domains_map(apps, self.primary)
        # Updated to match new exception message
        self.assertIn("already configured for", str(cm.exception))

    def test_invalid_canonical_type(self):
        apps = {"web-app-app1": {"domains": {"canonical": 123}}}
        with self.assertRaises(AnsibleFilterError):
            self.filter_module.canonical_domains_map(apps, self.primary)

    def test_non_auto_prefix_without_canonical_is_ignored(self):
        """
        Roles outside the web-*/svc-db-* auto-default prefixes that do not
        declare an explicit canonical domain should be skipped entirely.
        """
        apps = {
            "sys-ctl-foo": {},
            "service-app-app2": {},
        }
        result = self.filter_module.canonical_domains_map(apps, self.primary)
        self.assertEqual(result, {})

    def test_non_auto_prefix_with_canonical_registers(self):
        """
        Any role declaring an explicit canonical domain should register
        regardless of prefix. Infra roles such as svc-prx-openresty rely
        on this so the tls lookup can resolve them.
        """
        apps = {
            "svc-prx-openresty": {"domains": {"canonical": ["example.com"]}},
            "db-app-app1": {"domains": {"canonical": ["db.example.com"]}},
        }
        result = self.filter_module.canonical_domains_map(apps, self.primary)
        self.assertEqual(result["svc-prx-openresty"], ["example.com"])
        self.assertEqual(result["db-app-app1"], ["db.example.com"])

    def test_mixed_auto_default_and_explicit_canonical(self):
        """
        Auto-default domain generation still only applies to web-*/svc-db-*;
        other roles are included only when they declare a canonical domain.
        """
        apps = {
            "db-app-app1": {"domains": {"canonical": ["db.example.com"]}},
            "web-app-app1": {},
            "sys-ctl-noop": {},
        }
        expected = {
            "db-app-app1": ["db.example.com"],
            "web-app-app1": ["app1.example.com"],
        }
        result = self.filter_module.canonical_domains_map(apps, self.primary)
        self.assertEqual(result, expected)

    def test_non_auto_prefix_invalid_config_no_error(self):
        """
        Invalid configurations for roles outside the auto-default prefixes
        should not raise errors since they are skipped by the filter.
        """
        apps = {"nonweb-app-app1": "not-a-dict", "another": 12345}
        # Should simply return an empty result without exceptions
        result = self.filter_module.canonical_domains_map(apps, self.primary)
        self.assertEqual(result, {})

    def test_domain_primary_jinja_env_lookup_is_resolved(self):
        """
        DOMAIN_PRIMARY arrives as the raw Jinja template
        '{{ lookup(\\'env\\', \\'DOMAIN\\') | default(...) }}' when group_vars
        templating has not been forced. The filter MUST resolve it via the
        env-lookup fallback before composing default domains, otherwise the
        unrendered string ends up as a vhost server_name and breaks nginx.
        """
        import os

        prev = os.environ.get("DOMAIN")
        os.environ["DOMAIN"] = "infinito.example"
        try:
            primary = (
                "{{ lookup('env', 'DOMAIN') | default('infinito.localhost', true) }}"
            )
            apps = {"web-app-app1": {}}
            result = self.filter_module.canonical_domains_map(apps, primary)
            self.assertEqual(result, {"web-app-app1": ["app1.infinito.example"]})
        finally:
            if prev is None:
                os.environ.pop("DOMAIN", None)
            else:
                os.environ["DOMAIN"] = prev

    def test_domain_primary_unresolvable_jinja_raises(self):
        """
        If DOMAIN_PRIMARY contains a non-env Jinja expression the filter
        cannot resolve, fail loudly instead of emitting an unrendered string
        that would land in nginx configs.
        """
        primary = "{{ SOME_UNDEFINED_VAR }}"
        apps = {"web-app-app1": {}}
        with self.assertRaises(AnsibleFilterError):
            self.filter_module.canonical_domains_map(apps, primary)


if __name__ == "__main__":
    unittest.main()
