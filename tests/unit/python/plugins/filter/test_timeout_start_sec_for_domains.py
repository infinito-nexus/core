import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.timeout_start_sec_for_domains import FilterModule


def _f():
    return FilterModule().filters()["timeout_start_sec_for_domains"]


class TestTimeoutStartSecForDomains(unittest.TestCase):
    def test_basic_calculation_with_www(self):
        domains = {
            "canonical": ["example.com", "foo.bar"],
            "api": {"a": "api.example.com"},
        }
        result = _f()(
            domains,
            include_www=True,
            per_domain_seconds=25,
            overhead_seconds=30,
            min_seconds=120,
            max_seconds=3600,
        )
        self.assertEqual(result, 180)

    def test_no_www_min_clamp_applies(self):
        domains = {
            "canonical": ["example.com", "foo.bar"],
            "api": {"a": "api.example.com"},
        }
        result = _f()(
            domains,
            include_www=False,
            per_domain_seconds=25,
            overhead_seconds=30,
            min_seconds=120,
            max_seconds=3600,
        )
        self.assertEqual(result, 120)

    def test_max_clamp_applies(self):
        many = [f"host{i}.example.com" for i in range(150)]
        domains = {"canonical": many}
        result = _f()(
            domains,
            include_www=False,
            per_domain_seconds=25,
            overhead_seconds=30,
            min_seconds=120,
            max_seconds=3600,
        )
        self.assertEqual(result, 3600)

    def test_deduplication_of_domains(self):
        domains = {
            "a": ["x.com", "x.com"],
            "b": "x.com",
            "c": {"k": "x.com"},
        }
        result = _f()(
            domains,
            include_www=False,
            per_domain_seconds=25,
            overhead_seconds=30,
            min_seconds=120,
            max_seconds=3600,
        )
        self.assertEqual(result, 120)

    def test_deduplication_with_www_variants(self):
        domains = {
            "canonical": ["a.com", "b.com", "www.a.com"],
            "extra": {"x": "a.com"},
        }
        result = _f()(
            domains,
            include_www=True,
            per_domain_seconds=25,
            overhead_seconds=30,
            min_seconds=1,
            max_seconds=10000,
        )
        self.assertEqual(result, 130)

    def test_raises_on_invalid_type_int(self):
        with self.assertRaises(AnsibleFilterError):
            _f()(123)

    def test_raises_on_invalid_type_none(self):
        with self.assertRaises(AnsibleFilterError):
            _f()(None)

    def test_accepts_list_input(self):
        domains_list = ["a.com", "www.a.com", "b.com"]
        result = _f()(
            domains_list,
            include_www=True,
            per_domain_seconds=25,
            overhead_seconds=30,
            min_seconds=1,
            max_seconds=10000,
        )
        self.assertEqual(result, 30 + 25 * 4)

    def test_accepts_str_input(self):
        result = _f()(
            "a.com",
            include_www=True,
            per_domain_seconds=25,
            overhead_seconds=30,
            min_seconds=1,
            max_seconds=10000,
        )
        self.assertEqual(result, 30 + 25 * 2)


if __name__ == "__main__":
    unittest.main()
