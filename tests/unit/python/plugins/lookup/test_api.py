import unittest

from ansible.errors import AnsibleError

from plugins.lookup.api import LookupModule


class _FakeTemplar:
    """Minimal templar: deep-substitutes string leaves via ``mapping``."""

    def __init__(self, mapping=None, available=None):
        self._mapping = mapping or {}
        self.available_variables = available or {}

    def template(self, value):
        if isinstance(value, dict):
            return {k: self.template(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.template(v) for v in value]
        return self._mapping.get(value, value)


class TestApiLookup(unittest.TestCase):
    def setUp(self):
        self.lookup = LookupModule()
        self.api = {
            "cloudflare": {"api_token": "cf-token"},
            "telegram": {"bot_token": "", "api_id": "12345", "api_hash": "h"},
            "github": {"client_id": "gh-id", "client_secret": "gh-secret"},
        }
        self.vars = {"API": self.api}

    def test_resolves_nested_scalar(self):
        out = self.lookup.run(["cloudflare.api_token"], variables=self.vars)
        self.assertEqual(out, ["cf-token"])

    def test_resolves_deeper_provider_key(self):
        self.assertEqual(
            self.lookup.run(["github.client_secret"], variables=self.vars)[0],
            "gh-secret",
        )

    def test_resolves_empty_string_value(self):
        self.assertEqual(
            self.lookup.run(["telegram.bot_token"], variables=self.vars)[0], ""
        )

    def test_returns_subtree_when_path_is_provider_only(self):
        self.assertEqual(
            self.lookup.run(["cloudflare"], variables=self.vars)[0],
            {"api_token": "cf-token"},
        )

    def test_path_is_stripped(self):
        self.assertEqual(
            self.lookup.run(["  cloudflare.api_token  "], variables=self.vars)[0],
            "cf-token",
        )

    def test_unknown_provider_raises(self):
        with self.assertRaises(AnsibleError) as ctx:
            self.lookup.run(["nope.client_id"], variables=self.vars)
        self.assertIn("nope", str(ctx.exception))

    def test_unknown_leaf_key_raises_at_failing_part(self):
        with self.assertRaises(AnsibleError) as ctx:
            self.lookup.run(["cloudflare.missing"], variables=self.vars)
        msg = str(ctx.exception)
        self.assertIn("cloudflare.missing", msg)
        self.assertIn("missing", msg)

    def test_descend_into_scalar_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["cloudflare.api_token.extra"], variables=self.vars)

    def test_no_terms_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run([], variables=self.vars)

    def test_too_many_terms_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["a.b", "c.d"], variables=self.vars)

    def test_empty_path_raises(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["   "], variables=self.vars)

    def test_api_not_a_mapping_raises(self):
        with self.assertRaises(AnsibleError) as ctx:
            self.lookup.run(["cloudflare.api_token"], variables={"API": "nope"})
        self.assertIn("mapping", str(ctx.exception))

    def test_missing_api_global_raises_unknown_key(self):
        with self.assertRaises(AnsibleError):
            self.lookup.run(["cloudflare.api_token"], variables={})

    def test_templar_resolves_jinja_values(self):
        self.lookup._templar = _FakeTemplar(mapping={"{{ vault_cf }}": "secret-cf"})
        out = self.lookup.run(
            ["cloudflare.api_token"],
            variables={"API": {"cloudflare": {"api_token": "{{ vault_cf }}"}}},
        )
        self.assertEqual(out, ["secret-cf"])

    def test_falls_back_to_templar_available_variables(self):
        self.lookup._templar = _FakeTemplar(available={"API": self.api})
        self.assertEqual(
            self.lookup.run(["telegram.api_id"], variables=None)[0], "12345"
        )


if __name__ == "__main__":
    unittest.main()
