import importlib.util
import unittest

from . import PROJECT_ROOT


def _load_module():
    """
    Load the wildcard_dns filter plugin from:
      roles/sys-dns-wildcards/filter_plugins/wildcard_dns.py
    """
    path = (
        PROJECT_ROOT
        / "roles"
        / "sys-dns-wildcards"
        / "filter_plugins"
        / "wildcard_dns.py"
    )
    if not path.exists():
        raise FileNotFoundError(f"Could not find {path}")

    spec = importlib.util.spec_from_file_location("wildcard_dns", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


_wildcard_dns = _load_module()


def _get_filter():
    """Return the wildcard_records filter function from the plugin."""
    fm = _wildcard_dns.FilterModule()
    filters = fm.filters()
    if "wildcard_records" not in filters:
        raise AssertionError("wildcard_records filter not found")
    return filters["wildcard_records"]


def _as_set(records):
    """Normalize records for order-independent comparison."""
    return {
        (r.get("type"), r.get("name"), r.get("content"), bool(r.get("proxied")))
        for r in records
    }


class TestWildcardDNS(unittest.TestCase):
    def setUp(self):
        self.wildcard_records = _get_filter()

    def test_only_wildcards_including_apex(self):
        apex = "example.com"
        cpda = {
            "svc-a": ["c.wiki.example.com", "a.b.example.com"],
            "svc-b": {"extra": ["www.a.b.example.com"]},
            "svc-c": "example.com",
        }

        recs = self.wildcard_records(
            current_play_domains_all=cpda,
            apex=apex,
            ip4="203.0.113.10",
            ip6="2606:4700:4700::1111",
            proxied=True,
            explicit_domains=None,
            min_child_depth=2,
            ipv6_enabled=True,
        )

        got = _as_set(recs)
        expected = {
            # apex wildcard always
            ("A", "*", "203.0.113.10", True),
            ("AAAA", "*", "2606:4700:4700::1111", True),
            # derived parents
            ("A", "*.wiki", "203.0.113.10", True),
            ("AAAA", "*.wiki", "2606:4700:4700::1111", True),
            ("A", "*.b", "203.0.113.10", True),
            ("AAAA", "*.b", "2606:4700:4700::1111", True),
            # www.a.b.example.com promotes a.b.example.com as a parent
            ("A", "*.a.b", "203.0.113.10", True),
            ("AAAA", "*.a.b", "2606:4700:4700::1111", True),
        }
        self.assertEqual(got, expected)

    def test_min_child_depth_yields_only_apex(self):
        apex = "example.com"
        cpda = {"svc": ["x.example.com"]}  # depth = 1, below threshold

        recs = self.wildcard_records(
            current_play_domains_all=cpda,
            apex=apex,
            ip4="198.51.100.42",
            ip6="2606:4700:4700::1111",
            proxied=False,
            explicit_domains=None,
            min_child_depth=2,  # requires >= 2 → no parent derived
            ipv6_enabled=True,
        )
        got = _as_set(recs)
        expected = {
            ("A", "*", "198.51.100.42", False),
            ("AAAA", "*", "2606:4700:4700::1111", False),
        }
        self.assertEqual(got, expected)

    def test_ipv6_disabled_and_private_ipv6_filtered(self):
        apex = "example.com"
        cpda = {"svc": ["a.b.example.com"]}

        # IPv6 disabled → only A records (apex + parent)
        recs1 = self.wildcard_records(
            current_play_domains_all=cpda,
            apex=apex,
            ip4="203.0.113.9",
            ip6="2606:4700:4700::1111",
            proxied=False,
            explicit_domains=None,
            min_child_depth=2,
            ipv6_enabled=False,
        )
        self.assertEqual(
            _as_set(recs1),
            {
                ("A", "*", "203.0.113.9", False),
                ("A", "*.b", "203.0.113.9", False),
            },
        )

        # IPv6 enabled but ULA (not global) → skip AAAA (apex + parent)
        recs2 = self.wildcard_records(
            current_play_domains_all=cpda,
            apex=apex,
            ip4="203.0.113.9",
            ip6="fd00::1",
            proxied=False,
            explicit_domains=None,
            min_child_depth=2,
            ipv6_enabled=True,
        )
        self.assertEqual(
            _as_set(recs2),
            {
                ("A", "*", "203.0.113.9", False),
                ("A", "*.b", "203.0.113.9", False),
            },
        )

    def test_proxied_flag_true_is_set(self):
        recs = self.wildcard_records(
            current_play_domains_all={"svc": ["a.b.example.com"]},
            apex="example.com",
            ip4="203.0.113.7",
            ip6=None,
            proxied=True,
            explicit_domains=None,
            min_child_depth=2,
            ipv6_enabled=True,
        )
        self.assertTrue(all(r.get("proxied") is True for r in recs))
        self.assertEqual(
            _as_set(recs),
            {
                ("A", "*", "203.0.113.7", True),
                ("A", "*.b", "203.0.113.7", True),
            },
        )

    def test_explicit_domains_override_source(self):
        cpda = {"svc": ["ignore.me.example.com", "a.b.example.com"]}
        explicit = ["c.wiki.example.com"]

        recs = self.wildcard_records(
            current_play_domains_all=cpda,
            apex="example.com",
            ip4="203.0.113.5",
            ip6="2606:4700:4700::1111",
            proxied=False,
            explicit_domains=explicit,
            min_child_depth=2,
            ipv6_enabled=True,
        )
        self.assertEqual(
            _as_set(recs),
            {
                # apex wildcard always
                ("A", "*", "203.0.113.5", False),
                ("AAAA", "*", "2606:4700:4700::1111", False),
                # derived from explicit domain
                ("A", "*.wiki", "203.0.113.5", False),
                ("AAAA", "*.wiki", "2606:4700:4700::1111", False),
            },
        )

    def test_nested_structures_flattened_correctly(self):
        cpda = {
            "svc1": {
                "primary": ["c.wiki.example.com"],
                "extra": {"alt": ["a.b.example.com"]},
            },
            "svc2": "www.a.b.example.com",
            "svc3": ["x.example.net"],  # wrong apex → ignored
        }

        recs = self.wildcard_records(
            current_play_domains_all=cpda,
            apex="example.com",
            ip4="203.0.113.21",
            ip6="2606:4700:4700::1111",
            proxied=False,
            explicit_domains=None,
            min_child_depth=2,
            ipv6_enabled=True,
        )
        got = _as_set(recs)
        expected = {
            # apex wildcard always
            ("A", "*", "203.0.113.21", False),
            ("AAAA", "*", "2606:4700:4700::1111", False),
            # derived parents
            ("A", "*.wiki", "203.0.113.21", False),
            ("AAAA", "*.wiki", "2606:4700:4700::1111", False),
            ("A", "*.b", "203.0.113.21", False),
            ("AAAA", "*.b", "2606:4700:4700::1111", False),
            # www.a.b.example.com promotes a.b.example.com as a parent
            ("A", "*.a.b", "203.0.113.21", False),
            ("AAAA", "*.a.b", "2606:4700:4700::1111", False),
        }
        self.assertEqual(got, expected)

    def test_error_on_missing_ip4(self):
        from ansible.errors import AnsibleFilterError

        with self.assertRaises(AnsibleFilterError):
            self.wildcard_records(
                current_play_domains_all={"svc": ["a.b.example.com"]},
                apex="example.com",
                ip4="",  # must not be empty
                ip6=None,
                proxied=False,
                explicit_domains=None,
                min_child_depth=2,
                ipv6_enabled=True,
            )


if __name__ == "__main__":
    unittest.main()
