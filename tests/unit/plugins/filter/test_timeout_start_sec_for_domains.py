import unittest

from ansible.errors import AnsibleFilterError

from plugins.filter.timeout_start_sec_for_domains import FilterModule


def _f():
    return FilterModule().filters()["timeout_start_sec_for_domains"]


class TestTimeoutStartSecForDomains(unittest.TestCase):
    def test_basic_calculation_with_www(self):
        # 3 unique base domains → + www.* = 6 domains
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
        # raw = 30 + 25 * 6 = 180
        self.assertEqual(result, 180)

    def test_no_www_min_clamp_applies(self):
        # 3 unique domains, no www.* → raw = 30 + 25*3 = 105 → clamped to min=120
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
        # >143 domains needed to exceed 3600 (25s each + 30 overhead)
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
        # All entries resolve to "x.com" → only 1 unique domain
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
        # raw = 30 + 25 * 1 = 55 → clamped to 120
        self.assertEqual(result, 120)

    def test_deduplication_with_www_variants(self):
        # 2 unique base domains, one already includes a "www.a.com"
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
        # Unique: {"a.com","b.com","www.a.com","www.b.com"} → 4
        # raw = 30 + 25*4 = 130
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
        # unique + www for b.com -> {"a.com","www.a.com","b.com","www.b.com"} = 4
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
        # {"a.com","www.a.com"} = 2
        self.assertEqual(result, 30 + 25 * 2)


if __name__ == "__main__":
    unittest.main()
