"""Lint guard: never glue a literal ``http://`` / ``https://`` in front of a
domain that comes from a ``lookup(...)`` (or from a ``domains.canonical``
member access). The protocol must come from the same source as the domain so
TLS-on / TLS-off / self-signed / public-CA stays consistent across the stack.

Background
==========
Each role's TLS posture is decided centrally (``TLS_ENABLED``, ``TLS_MODE``,
the role's own ``server.tls`` overrides). The ``tls`` lookup plugin reads
that decision and emits the right protocol next to the domain:

* ``lookup('tls', '<role>', 'url.base')``         → ``https://<canonical>/``
* ``lookup('tls', '<role>', 'protocols.web')``    → ``https`` or ``http``
* ``lookup('tls', '<role>', 'protocols.websocket')`` → ``wss`` or ``ws``

Hand-written ``"https://" ~ lookup('domain', '<role>')`` (or
``"https://{{ lookup('domain', '<role>') }}"``) hard-codes the protocol and
silently breaks the moment TLS gets disabled in dev, gets switched to a
different flavor, or the role is moved behind a different proxy.

Allowed
=======
* Opt-out via ``# nocheck: literal-protocol-lookup`` (case-insensitive) on the
  offending line or the one immediately above it. The line above is not a
  convenience: a value long enough to be flagged is long enough for the YAML
  formatter to wrap it, and a wrapped value cannot carry a trailing marker at
  all - the ``#`` would land inside the quoted scalar. Use this
  for legitimate internal cases where the protocol is genuinely fixed —
  Docker-network upstreams that always speak plaintext (``http://<container>:<port>``),
  loopback URLs in CI fixtures, and similar.

Detection
=========
The regex catches three concrete shapes:

1. ``https?://{{ ... lookup( ... }}``    — Jinja interpolation with a lookup
2. ``"https?://" ~ lookup(...)``         — Jinja string concatenation with lookup
3. ``"https?://" ~ ... canonical.<key>`` — concatenation with a
   ``domains.canonical`` member access.

Plain ``"http://" ~ host ~ ":" ~ port`` style internal URLs (the protocol is
fixed because the upstream is on a docker network with no TLS) are *not*
detected because the pattern requires a ``lookup(`` or ``canonical.`` token.
File reads and the per-file scan results are cached process-wide.
"""

from __future__ import annotations

import re
import unittest
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

if TYPE_CHECKING:
    from collections.abc import Iterable

_RULE = "literal-protocol-lookup"

_INTERP_RE: re.Pattern[str] = re.compile(r"https?://\{\{[^}]*\blookup\s*\(")
_CONCAT_LOOKUP_RE: re.Pattern[str] = re.compile(
    r"['\"]https?://['\"]\s*~\s*\(?\s*\blookup\s*\("
)
_CONCAT_CANONICAL_RE: re.Pattern[str] = re.compile(
    r"['\"]https?://['\"]\s*~[^'\"]*\bcanonical\b"
)

ROLES_DIR = PROJECT_ROOT / "roles"


def _suppressed_for_value(lines: list[str], idx: int) -> bool:
    """Whether the value starting at 1-based *idx* carries the marker.

    A wrapped value keeps its trailing comment on the last line, while the
    offence is reported on the first, so the continuation lines count too.
    """
    if is_suppressed_at(lines, idx, _RULE):
        return True
    for following in range(idx + 1, len(lines) + 1):
        text = lines[following - 1]
        if not text[:1].isspace():
            return False
        if is_suppressed_at(lines, following, _RULE, mode="same-line"):
            return True
    return False


@lru_cache(maxsize=8192)
def _file_offenders(path: Path) -> tuple[str, ...]:
    name = path.name
    if name.lower() == "readme.md":
        return ()

    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return ()

    if "://" not in text:
        return ()

    lines = text.splitlines()

    offenders: list[str] = []
    for idx, line in enumerate(lines, start=1):
        if _suppressed_for_value(lines, idx):
            continue
        snippet: str | None = None
        for pattern in (_INTERP_RE, _CONCAT_LOOKUP_RE, _CONCAT_CANONICAL_RE):
            match = pattern.search(line)
            if match:
                snippet = line.strip()
                break
        if snippet is None:
            continue
        offenders.append(
            f"line {idx}: {snippet} (use lookup('tls', '<role>', 'url.base') "
            f"so the protocol is derived from TLS state)"
        )

    return tuple(offenders)


def _scan_paths() -> Iterable[Path]:
    for s in iter_project_files(exclude_tests=True, exclude_dirs=("docs",)):
        p = Path(s)
        try:
            rel = p.relative_to(ROLES_DIR)
        except ValueError:
            continue
        if any(seg in {"docs", "files"} for seg in rel.parts[:-1]):
            continue
        yield p


class TestLiteralProtocolWithLookup(unittest.TestCase):
    """Pinning ``http://`` / ``https://`` next to a domain-resolving lookup
    breaks TLS-mode-aware routing."""

    def test_no_literal_protocol_glued_to_lookup(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for path in _scan_paths():
            issues = list(_file_offenders(path))
            if issues:
                offenders[path] = issues

        if not offenders:
            return

        rel = lambda p: p.relative_to(PROJECT_ROOT)  # noqa: E731
        lines = [
            (
                f"{len(offenders)} file(s) prepend a literal http(s):// to a "
                f"lookup-derived domain instead of letting the `tls` lookup "
                f"decide the protocol:"
            ),
        ]
        for path, issues in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            lines.extend(f"      * {issue}" for issue in issues)
        lines.append("")
        lines.append(
            "Fix: replace the literal-protocol concatenation with "
            "`{{ lookup('tls', '<role>', 'url.base') }}` (returns "
            "`<protocol>://<canonical>/`). When you only need the protocol "
            "fragment, use `{{ lookup('tls', '<role>', 'protocols.web') }}` "
            "or `protocols.websocket`."
        )
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
