from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class BuildContext:
    """Per-build inputs passed to every handler.

    Attributes are read-only; per-handler scratch state lives on the
    :class:`EnvBuilder` instead.
    """

    static: dict[str, str]
    static_comments: dict[str, str]
    repo_root: Path
    on_gha: bool
    on_act: bool


class EnvBuilder:
    """Mirror bash ``: "${KEY:=value}"`` semantics with per-key comments.

    ``setdefault`` falls back to the supplied value only when the
    process env has no non-empty value for the key. ``set`` is
    unconditional. ``get`` reads from the builder, falling back to the
    process env so derived values (e.g. ``INFINITO_CONTAINER``) can be
    composed off previously-set keys.
    """

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.comments: dict[str, str] = {}

    def setdefault(self, key: str, value: str, *, comment: str = "") -> str:
        existing = os.environ.get(key, "").strip()
        self.values[key] = existing or value
        if comment:
            self.comments.setdefault(key, comment)
        return self.values[key]

    def set(self, key: str, value: str, *, comment: str = "") -> str:
        self.values[key] = value
        if comment:
            self.comments.setdefault(key, comment)
        return value

    def get(self, key: str) -> str:
        return self.values.get(key, os.environ.get(key, ""))
