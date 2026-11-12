from __future__ import annotations

import unittest

from plugins.filter.litellm.local_model import (
    local_model_refusal,
    local_models_missing,
)

_COMMIT = "199151125cf15a129ab3b548b26afeed976df066"
_SHA = "f7ede42862ceca07ad1c88a97b67520019c4ac7e5ced250d2e696fa62ab189af"
_URL = (
    "https://huggingface.co/lmstudio-community/Llama-3.2-1B-Instruct-GGUF/"
    "resolve/{ref}/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
)
_PINNED = {
    "alias": "llama3.2:1b",
    "url": _URL.format(ref=_COMMIT),
    "revision": _COMMIT,
    "sha256": _SHA,
    "bytes": 807690688,
}


class TestLocalModelRefusal(unittest.TestCase):
    def test_a_file_pinned_to_one_commit_passes(self) -> None:
        self.assertEqual("", local_model_refusal(_PINNED))

    def test_a_url_on_a_branch_is_refused(self) -> None:
        refusal = local_model_refusal(dict(_PINNED, url=_URL.format(ref="main")))
        self.assertIn("ref segment 'main'", refusal)

    def test_a_branch_as_revision_is_refused(self) -> None:
        refusal = local_model_refusal(
            dict(_PINNED, url=_URL.format(ref="main"), revision="main")
        )
        self.assertIn("40-digit lowercase hex commit", refusal)

    def test_a_missing_digest_is_refused(self) -> None:
        refusal = local_model_refusal(dict(_PINNED, sha256=""))
        self.assertIn("sha256", refusal)

    def test_a_missing_size_is_refused(self) -> None:
        unsized = {key: value for key, value in _PINNED.items() if key != "bytes"}
        self.assertIn("bytes", local_model_refusal(unsized))

    def test_a_library_tag_is_refused(self) -> None:
        refusal = local_model_refusal({"alias": "qwen2.5:0.5b", "context": 4096})
        self.assertIn("revision", refusal)
        self.assertIn("sha256", refusal)

    def test_a_bare_tag_string_is_refused(self) -> None:
        self.assertIn("not a mapping", local_model_refusal("qwen2.5:0.5b"))


class TestLocalModelsMissing(unittest.TestCase):
    def test_a_model_held_at_its_pinned_blob_is_present(self) -> None:
        held = {
            "model": _PINNED,
            "stdout": f"FROM /root/.ollama/models/blobs/sha256-{_SHA}\n",
        }
        self.assertEqual([], local_models_missing([held]))

    def test_a_model_held_at_another_blob_is_missing(self) -> None:
        other = {
            "model": _PINNED,
            "stdout": "FROM /root/.ollama/models/blobs/sha256-" + "0" * 64,
        }
        self.assertEqual([_PINNED], local_models_missing([other]))

    def test_an_absent_model_is_missing(self) -> None:
        absent = {"model": _PINNED, "stdout": "", "rc": 1}
        self.assertEqual([_PINNED], local_models_missing([absent]))

    def test_no_results_means_nothing_missing(self) -> None:
        self.assertEqual([], local_models_missing(None))


if __name__ == "__main__":
    unittest.main()
