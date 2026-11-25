from __future__ import annotations

import http.client
import lzma
import unittest
import unittest.mock
import urllib.parse
from collections.abc import Callable

from tests.external.repository import _package_probes as probes
from utils.env.parser import env_setting
from utils.packages.schema import SOURCE_REPO

MIRRORS = env_setting(probes.UBUNTU_MIRRORS_KEY).split()

Answer = Callable[[str], tuple[int, bytes] | BaseException | None]


def _host(url: str) -> str | None:
    return urllib.parse.urlsplit(url).hostname


FIRST, SECOND = (_host(mirror) for mirror in MIRRORS[:2])


def _index(*names: str) -> tuple[int, bytes]:
    return 200, lzma.compress("".join(f"Package: {n}\n\n" for n in names).encode())


def _probe(distro: str, name: str, answer: Answer) -> tuple[probes.Outcome, list[str]]:
    requested: list[str] = []

    def fetch(url: str) -> tuple[int, bytes]:
        requested.append(url)
        reply = answer(url)
        if reply is None:
            raise TimeoutError("timed out")
        if isinstance(reply, BaseException):
            raise reply
        return reply

    with (
        unittest.mock.patch.dict(probes._APT_INDEX_CACHE, clear=True),
        unittest.mock.patch.object(probes, "_get", fetch),
    ):
        outcome = probes._probe(probes.Probe("pkg", distro, name, None, SOURCE_REPO))
    return outcome, requested


class TestUbuntuIndexMirrorFallback(unittest.TestCase):
    def test_a_timed_out_first_mirror_falls_back_to_the_second(self) -> None:
        outcome, requested = _probe(
            "ubuntu", "0ad", lambda url: _index("0ad") if _host(url) == SECOND else None
        )

        self.assertIs(outcome.available, True, outcome.detail)
        self.assertIn(SECOND, outcome.detail)
        self.assertEqual(_host(requested[0]), FIRST)
        self.assertEqual({_host(url) for url in requested}, {FIRST, SECOND})

    def test_every_mirror_failing_leaves_availability_unknown(self) -> None:
        outcome, _ = _probe("ubuntu", "0ad", lambda url: None)

        self.assertIsNone(outcome.available)
        self.assertFalse(outcome.declared)
        self.assertEqual(
            [part.split(":")[0] for part in outcome.detail.split("; ")],
            [_host(mirror) for mirror in MIRRORS],
        )

    def test_a_broken_http_response_falls_back_to_the_next_mirror(self) -> None:
        def answer(url: str) -> tuple[int, bytes] | BaseException:
            if _host(url) == FIRST:
                return http.client.IncompleteRead(b"")
            return _index("0ad")

        outcome, _ = _probe("ubuntu", "0ad", answer)

        self.assertIs(outcome.available, True, outcome.detail)
        self.assertIn(SECOND, outcome.detail)

    def test_a_pocket_one_mirror_lacks_moves_the_whole_index_on(self) -> None:
        def answer(url: str) -> tuple[int, bytes]:
            if _host(url) != FIRST:
                return _index("0ad")
            return (404, b"") if "-updates/" in url else _index("first-only")

        outcome, requested = _probe("ubuntu", "first-only", answer)

        self.assertIs(outcome.available, False, outcome.detail)
        self.assertIn(SECOND, outcome.detail)
        index = probes.APT_INDEX["ubuntu"]
        self.assertEqual(
            sum(_host(url) == SECOND for url in requested),
            len(index.suites) * len(index.components),
        )

    def test_a_name_the_serving_mirror_lacks_is_absent(self) -> None:
        outcome, requested = _probe(
            "ubuntu",
            "missing",
            lambda url: _index("0ad") if _host(url) == FIRST else None,
        )

        self.assertIs(outcome.available, False, outcome.detail)
        self.assertIn(FIRST, outcome.detail)
        self.assertEqual({_host(url) for url in requested}, {FIRST})


class TestDebianIndex(unittest.TestCase):
    def test_debian_reads_deb_debian_org(self) -> None:
        outcome, requested = _probe("debian", "0ad", lambda url: _index("0ad"))

        self.assertIs(outcome.available, True, outcome.detail)
        self.assertEqual({_host(url) for url in requested}, {"deb.debian.org"})
        self.assertTrue(all("/debian/dists/stable" in url for url in requested))


if __name__ == "__main__":
    unittest.main()
