from __future__ import annotations

import importlib.util
import unittest
import urllib.error
from unittest import mock

from . import PROJECT_ROOT

_SOURCE = PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "test" / "extract.py"
_spec = importlib.util.spec_from_file_location("docs_test_extract", _SOURCE)
extract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(extract)

PAGE = """\
<section id="quick-setup"><h2>Quick Setup</h2>
<section id="development"><h3>Development</h3>
<div class="highlight-bash"><div class="highlight"><pre><span></span>\
<span class="nb">make</span> onboard
</pre></div></div>
</section>
<section id="production"><h3>Production</h3>
<div class="highlight-bash"><div class="highlight"><pre><span></span>\
<span class="nv">APP</span><span class="o">=</span>web-app-x
<span class="nb">echo</span> <span class="s2">&quot;a &amp; b&quot;</span>
</pre></div></div>
</section></section>
"""

WITHOUT = '<section id="overview"><h2>Overview</h2><p>No setup here.</p></section>'


class TestBlock(unittest.TestCase):
    def _parsed(self, page: str) -> str:
        parser = extract.Block()
        parser.feed(page)
        return parser.text

    def test_it_takes_the_block_below_the_production_heading(self) -> None:
        text = self._parsed(PAGE)

        self.assertIn("APP=web-app-x", text)
        self.assertNotIn("make onboard", text)

    def test_entities_come_back_as_characters(self) -> None:
        self.assertIn('"a & b"', self._parsed(PAGE))

    def test_highlight_markup_does_not_reach_the_commands(self) -> None:
        self.assertNotIn("<span", self._parsed(PAGE))

    def test_a_page_without_the_heading_yields_nothing(self) -> None:
        self.assertEqual(self._parsed(WITHOUT).strip(), "")


class TestPageUrl(unittest.TestCase):
    def test_it_addresses_the_latest_version(self) -> None:
        self.assertEqual(
            extract.page_url("http://host:8036/", "web-app-x"),
            "http://host:8036/latest/roles/web-app-x/README.html",
        )


class TestFetch(unittest.TestCase):
    def _response(self, status: int, body: bytes = b"<html></html>"):
        response = mock.MagicMock()
        response.status = status
        response.read.return_value = body
        response.__enter__.return_value = response
        return response

    def test_a_ready_page_is_returned_at_once(self) -> None:
        with mock.patch.object(extract.urllib.request, "urlopen") as opener:
            opener.return_value = self._response(200, b"<p>ok</p>")

            self.assertEqual(extract.fetch("http://x/", timeout=1), "<p>ok</p>")

    def test_it_waits_while_the_version_is_building(self) -> None:
        answers = [self._response(202), self._response(200, b"<p>ok</p>")]
        with (
            mock.patch.object(extract.urllib.request, "urlopen", side_effect=answers),
            mock.patch.object(extract.time, "sleep"),
        ):
            self.assertEqual(
                extract.fetch("http://x/", timeout=60, poll=0), "<p>ok</p>"
            )

    def test_a_build_that_never_finishes_times_out(self) -> None:
        with (
            mock.patch.object(extract.urllib.request, "urlopen") as opener,
            mock.patch.object(extract.time, "sleep"),
        ):
            opener.return_value = self._response(202)
            with self.assertRaises(TimeoutError):
                extract.fetch("http://x/", timeout=0, poll=0)

    def test_an_error_other_than_building_is_raised(self) -> None:
        failure = urllib.error.HTTPError("http://x/", 404, "gone", {}, None)
        with (
            mock.patch.object(extract.urllib.request, "urlopen", side_effect=failure),
            self.assertRaises(urllib.error.HTTPError),
        ):
            extract.fetch("http://x/", timeout=1)


class TestBlockEntry(unittest.TestCase):
    def test_a_page_without_instructions_is_an_error(self) -> None:
        with (
            mock.patch.object(extract, "fetch", return_value=WITHOUT),
            self.assertRaises(ValueError),
        ):
            extract.block("http://x/", "web-app-x", timeout=1)


if __name__ == "__main__":
    unittest.main()
