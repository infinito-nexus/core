"""Unit tests for :mod:`utils.install.github_release`."""

from __future__ import annotations

import unittest
import unittest.mock as mock

from utils.install import github_release as gr


class _FakeResp:
    def __init__(self, final_url: str) -> None:
        self._final = final_url

    def __enter__(self) -> _FakeResp:  # noqa: PYI034 - test double, not a Self-typed lib
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def geturl(self) -> str:
        return self._final


class TestResolveLatestTag(unittest.TestCase):
    def test_strips_leading_v(self) -> None:
        with mock.patch.object(
            gr,
            "urlopen",
            return_value=_FakeResp("https://example.com/x/y/releases/tag/v1.2.3"),
        ):
            self.assertEqual(
                gr.resolve_latest_tag("https://example.com/x/y/releases/latest"),
                "1.2.3",
            )

    def test_handles_trailing_slash(self) -> None:
        with mock.patch.object(
            gr,
            "urlopen",
            return_value=_FakeResp("https://example.com/x/y/releases/tag/v9.0.0/"),
        ):
            self.assertEqual(gr.resolve_latest_tag("https://example/latest"), "9.0.0")

    def test_raises_when_unresolved(self) -> None:
        latest = "https://example.com/x/y/releases/latest"
        with mock.patch.object(gr, "urlopen", return_value=_FakeResp(latest)):
            self.assertRaises(RuntimeError, gr.resolve_latest_tag, latest)

    def test_raises_when_tag_is_literal_latest(self) -> None:
        with mock.patch.object(
            gr,
            "urlopen",
            return_value=_FakeResp("https://example.com/x/y/releases/tag/latest"),
        ):
            self.assertRaises(
                RuntimeError, gr.resolve_latest_tag, "https://example/latest"
            )


class TestDownloadReleaseAsset(unittest.TestCase):
    def test_delegates_to_download_file(self) -> None:
        with mock.patch.object(gr, "download_file") as dl:
            gr.download_release_asset("https://example/x.tar.gz", "/tmp/x.tar.gz")
        dl.assert_called_once_with("https://example/x.tar.gz", "/tmp/x.tar.gz")


if __name__ == "__main__":
    unittest.main()
