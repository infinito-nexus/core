"""An ``AI_LOCAL_MODELS`` entry names one quantization in every field.

Rationale
=========
``roles/svc-ai-lmstudio/tasks/utils/preload/pull.yml`` downloads with
``lms get --yes --gguf <source>@<quant>``. Without the ``@<quant>`` suffix LM
Studio picks the variant itself, and the ``file``, ``sha256`` and ``bytes`` the
entry declares become a guess about that pick rather than a description of it.

Two shipped checks measure against those fields, so the guess is not harmless.
``roles/svc-ai-lmstudio/files/test/test.sh`` looks for
``<models>/<repo>/<file>`` and reports ``is not in the model store`` when the
store holds a different variant. ``pull.yml`` derives the download budget from
``bytes``, so a declaration smaller than the real file cuts the transfer off.

Run 36107421422 hit both at once: the entry declared ``Q4_K_M`` at 808 MB while
``lms get`` fetched ``Q8_0`` at 1.32 GB. The declared quantization is therefore
pinned here against the other three fields, because an entry whose fields
disagree fails far from the line that introduced the disagreement.

Per-line opt-out
================
Add ``# nocheck: local-model-quant-pinned`` on the offending line or the one
above it, with a comment naming why the fields may diverge.
"""

from __future__ import annotations

import unittest
from typing import ClassVar

import yaml

from utils.annotations.suppress import is_suppressed_at

from . import PROJECT_ROOT

_RULE = "local-model-quant-pinned"
_VARS_FILE = PROJECT_ROOT / "group_vars" / "all" / "16_ai.yml"
_KEY = "AI_LOCAL_MODELS"


def _entries() -> list[dict]:
    data = yaml.safe_load(_VARS_FILE.read_text(encoding="utf-8")) or {}
    declared = data.get(_KEY)
    return [entry for entry in (declared or []) if isinstance(entry, dict)]


def _line_of(alias: str) -> int:
    for number, line in enumerate(
        _VARS_FILE.read_text(encoding="utf-8").splitlines(), 1
    ):
        if f"alias: {alias}" in line:
            return number
    return 0


class TestLocalModelQuantPinned(unittest.TestCase):
    rel: ClassVar[str] = _VARS_FILE.relative_to(PROJECT_ROOT).as_posix()

    def _unsuppressed(self) -> list[dict]:
        return [
            entry
            for entry in _entries()
            if not is_suppressed_at(
                str(_VARS_FILE), _line_of(str(entry.get("alias", ""))), _RULE
            )
        ]

    def test_every_entry_pins_a_quantization(self) -> None:
        missing = [
            entry.get("alias")
            for entry in self._unsuppressed()
            if not str(entry.get("quant") or "").strip()
        ]
        self.assertFalse(
            missing,
            f"{self.rel}: {missing} declare no 'quant', so lms get picks the "
            "variant and the declared file, sha256 and bytes describe a guess",
        )

    def test_the_declared_file_carries_the_pinned_quantization(self) -> None:
        drifted = [
            (entry.get("alias"), entry.get("quant"), entry.get("file"))
            for entry in self._unsuppressed()
            if str(entry.get("quant") or "").strip()
            and str(entry.get("quant")).lower()
            not in str(entry.get("file") or "").lower()
        ]
        self.assertFalse(
            drifted,
            f"{self.rel}: {drifted} name a quantization the file does not "
            "carry; the store check looks for that file and reports it missing",
        )

    def test_the_url_resolves_the_declared_file(self) -> None:
        drifted = [
            (entry.get("alias"), entry.get("file"))
            for entry in self._unsuppressed()
            if not str(entry.get("url") or "").endswith(str(entry.get("file") or ""))
        ]
        self.assertFalse(
            drifted,
            f"{self.rel}: {drifted} declare a url that does not end in the "
            "declared file, so the digest is pinned against a different blob",
        )


if __name__ == "__main__":
    unittest.main()
