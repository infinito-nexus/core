"""Compose the `.env` value-set from static defaults plus runtime context.

Thin orchestrator: each variable's mapping/computation lives in its own
module under :mod:`utils.env.handlers`. ``build_env`` walks the
``ORDERED_HANDLERS`` registry, letting each handler read/write through
an :class:`EnvBuilder`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.env.handlers import ORDERED_HANDLERS
from utils.env.runtime import detect_gha_act

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


def apply_custom_env(eb: EnvBuilder, repo_root: Path) -> None:
    """Overwrite every key found in ``<repo_root>/custom.env``.

    ``custom.env`` is the operator's untracked override file; its values
    win over static defaults AND handler-computed values.
    """
    from utils.env.parser import parse_static_env_with_comments

    custom_path = repo_root / "custom.env"
    if not custom_path.is_file():
        return
    custom, custom_comments = parse_static_env_with_comments(custom_path)
    for key, value in custom.items():
        eb.set(key, value)
        eb.comments[key] = custom_comments.get(key) or eb.comments.get(key, "")


def build_env(
    static: dict[str, str],
    repo_root: Path,
    *,
    comments: dict[str, str] | None = None,
) -> EnvBuilder:
    """Compose the full env-set from ``static`` (parsed default.env) +
    runtime context resolved against ``repo_root``.

    ``comments`` is the parsed per-key comment map from default.env
    (see :func:`utils.env.parser.parse_static_env_with_comments`).
    Dynamic keys carry their comments via each handler's ``COMMENT``
    constant. ``custom.env`` overrides run last (see
    :func:`apply_custom_env`).
    """
    on_gha, on_act = detect_gha_act()
    ctx = BuildContext(
        static=static,
        static_comments=comments or {},
        repo_root=repo_root,
        on_gha=on_gha,
        on_act=on_act,
    )
    eb = EnvBuilder()
    for handler in ORDERED_HANDLERS:
        handler.apply(eb, ctx)
    apply_custom_env(eb, repo_root)
    return eb
