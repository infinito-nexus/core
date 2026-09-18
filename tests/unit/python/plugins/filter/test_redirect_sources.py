import sys
import unittest

from . import PROJECT_ROOT

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ansible.errors import AnsibleFilterError

from plugins.filter.redirect_sources import FilterModule, redirect_sources


class TestRedirectSources(unittest.TestCase):
    def test_every_reference_form_is_covered(self):
        self.assertEqual(
            redirect_sources("unpkg.com"),
            [
                "https://unpkg.com/",
                "http://unpkg.com/",
                "/",
            ],
        )

    def test_the_catch_all_comes_last(self):
        sources = redirect_sources("unpkg.com")

        self.assertEqual(
            sources[-1],
            "/",
            "the bare slash is the widest form and reads as the fallback only "
            "while it stays at the end",
        )

    def test_no_form_is_a_prefix_of_another(self):
        sources = redirect_sources("unpkg.com")

        for index, source in enumerate(sources):
            for other in sources[:index]:
                self.assertFalse(
                    source.startswith(other),
                    f"{source!r} starts with {other!r}, so the two forms "
                    f"cannot be told apart by a prefix comparison",
                )

    def test_surrounding_whitespace_is_dropped(self):
        self.assertEqual(redirect_sources("  unpkg.com  ")[0], "https://unpkg.com/")

    def test_the_host_is_not_otherwise_rewritten(self):
        self.assertEqual(
            redirect_sources("CDN.Example.COM")[1], "http://CDN.Example.COM/"
        )

    def test_a_subdomain_host_keeps_every_label(self):
        self.assertEqual(
            redirect_sources("cdn.jsdelivr.net")[0], "https://cdn.jsdelivr.net/"
        )

    def test_an_empty_host_is_rejected(self):
        for value in ("", "   "):
            with self.assertRaises(AnsibleFilterError):
                redirect_sources(value)

    def test_a_non_string_host_is_rejected(self):
        for value in (None, 42, ["unpkg.com"]):
            with self.assertRaises(AnsibleFilterError):
                redirect_sources(value)

    def test_the_filter_is_exported(self):
        self.assertIs(FilterModule().filters()["redirect_sources"], redirect_sources)


if __name__ == "__main__":
    unittest.main()
