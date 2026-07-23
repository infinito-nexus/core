"""Lint guard: literal ``<sub>.{{ DOMAIN_PRIMARY }}`` strings only belong to
``canonical`` / ``aliases`` in ``meta/domains.yml`` (and the
same lists inside ``meta/variants.yml``). Every other file MUST resolve a
role's domain through the project's lookup plugins so the canonical/aliases
entries stay the single point of truth.

Background
==========
Each role's ``meta/domains.yml`` defines its hostnames once via
``canonical`` and ``aliases``. Anything else that needs a
role's hostname (CSP whitelists, env vars, templates, tasks, configs) MUST
read it back through ``lookup('domain', '<role>')`` or
``lookup('tls', '<role>', 'url.base')``. Hand-written
``foo.{{ DOMAIN_PRIMARY }}`` strings outside the canonical/aliases lists
silently duplicate the SPOT and rot whenever a hostname moves.

Allowed
=======
* ``roles/<role>/meta/domains.yml`` inside the ``canonical`` and
  ``aliases`` list values (the SPOT itself).
* ``roles/<role>/meta/variants.yml`` inside any per-variant
  ``domains.canonical`` and ``domains.aliases`` list values
  (alternate SPOTs that the variant matrix selects between).
* Wildcard fragments without a leading subdomain word
  (``.{{ DOMAIN_PRIMARY }}`` and ``*.{{ DOMAIN_PRIMARY }}``) used for
  wildcard certs, oauth2-proxy whitelists, iframe origin checks, etc.
* ``README.md`` (documentation may mention example hostnames).
* Per-line opt-out: add ``# nocheck: domain-spot`` (case-insensitive)
  on the offending line.

Detection
=========
For every file under ``roles/`` (excluding ``README.md`` and
``docs/`` directories), scan each line for a regex matching a
``<word>.{{ DOMAIN_PRIMARY }}`` pattern. For ``meta/domains.yml`` and
``meta/variants.yml``, lines that materialize a value inside the
allowed ``canonical`` / ``aliases`` lists are exempted.
Everything else fails the lint with the offending file, line and
suggested ``lookup(...)`` replacement.
"""

from __future__ import annotations

import re
import unittest
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from utils.annotations.suppress import suppressed_line_numbers
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

if TYPE_CHECKING:
    from collections.abc import Iterable

# A leading word boundary plus at least one alphanumeric character before the
# dot ensures we only match `sub.{{ DOMAIN_PRIMARY }}` constructions, not
# wildcard fragments like `.{{ DOMAIN_PRIMARY }}` or `*.{{ DOMAIN_PRIMARY }}`.
_PATTERN: re.Pattern[str] = re.compile(
    r"(?<![A-Za-z0-9_-])([A-Za-z0-9][A-Za-z0-9.-]*)\.\{\{\s*DOMAIN_PRIMARY\s*\}\}"
)

ROLES_DIR = PROJECT_ROOT / "roles"


@lru_cache(maxsize=4096)
def _exempt_lines_for_lists(path: Path) -> frozenset[int]:
    """Find every list-item line that lives under
    ``canonical`` / ``aliases``. The same heuristic also
    covers ``meta/variants.yml``, since each variant block carries its own
    ``domains.canonical`` / ``aliases`` list and the canonical/aliases
    keys never appear elsewhere in role meta files.

    We do NOT load the YAML structurally because we want line numbers
    cheaply and tolerate Jinja-templated keys/values that are not valid
    pure YAML for some files. The state machine watches indentation and
    block headers; entries continue until indentation pops back at or
    above the list header.

    The result is cached per absolute path; repeat lookups during the
    test traversal pay only the first parse.
    """
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return frozenset()

    allowed: set[int] = set()
    lines = text.splitlines()
    inside_list = False
    list_indent = -1

    # We only need to recognise the headers `canonical:` and `aliases:`
    # appearing under the appropriate parent. A coarse "any line that
    # opens a canonical/aliases list" detection is enough because the
    # SPOT keys do not appear elsewhere in role meta files.
    header_re = re.compile(r"^(\s*)(canonical|aliases)\s*:\s*(?:#.*)?$")
    item_re = re.compile(r"^(\s*)-\s+")
    # Dict-style entry inside ``canonical:`` / ``aliases:`` (e.g. matrix's
    # ``synapse: matrix.{{ DOMAIN_PRIMARY }}`` or bluesky's per-service
    # canonical map). Lines look like ``<sp><key>: <value>`` at deeper
    # indent than the list header.
    dict_entry_re = re.compile(r"^(\s+)[A-Za-z0-9_-]+\s*:\s*\S")

    for idx, line in enumerate(lines, start=1):
        match = header_re.match(line)
        if match:
            inside_list = True
            list_indent = len(match.group(1))
            continue
        if not inside_list:
            continue

        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue

        item_match = item_re.match(line)
        if item_match and len(item_match.group(1)) >= list_indent:
            # YAML supports both compact (item at same indent as key) and
            # expanded (item at deeper indent) list styles for
            # ``canonical:`` / ``aliases:`` blocks; both are SPOTs.
            allowed.add(idx)
            continue

        dict_match = dict_entry_re.match(line)
        if dict_match and len(dict_match.group(1)) > list_indent:
            # Dict-style ``<key>: <value>`` inside the canonical/aliases
            # block (matrix, bluesky). Each value line is part of the SPOT.
            allowed.add(idx)
            continue

        # If we hit any non-item line that is at or above the list
        # indentation, the canonical/aliases block is over.
        line_indent = len(line) - len(stripped)
        if line_indent <= list_indent:
            inside_list = False
            list_indent = -1
            # Re-evaluate this same line as a potential new header.
            new_match = header_re.match(line)
            if new_match:
                inside_list = True
                list_indent = len(new_match.group(1))
            continue

    return frozenset(allowed)


@lru_cache(maxsize=8192)
def _file_offenders(path: Path) -> tuple[str, ...]:
    rel = path.relative_to(PROJECT_ROOT)
    name = path.name

    # README files are documentation; example hostnames belong there.
    if name.lower() == "readme.md":
        return ()

    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return ()

    if "DOMAIN_PRIMARY" not in text:
        return ()

    lines = text.splitlines()

    exempt: set[int] = set()
    parts = rel.parts
    if (
        len(parts) >= 3
        and parts[0] == "roles"
        and parts[2] == "meta"
        and name in {"domains.yml", "variants.yml"}
    ):
        exempt = _exempt_lines_for_lists(path)

    noqa_lines = suppressed_line_numbers(lines, "domain-spot")

    offenders: list[str] = []
    for idx, line in enumerate(lines, start=1):
        if idx in exempt or idx in noqa_lines:
            continue
        match = _PATTERN.search(line)
        if not match:
            continue
        offenders.append(
            f"line {idx}: {match.group(0)} (use lookup('domain', '<role>') or "
            f"lookup('tls', '<role>', 'url.base'))"
        )

    return tuple(offenders)


def _scan_paths() -> Iterable[Path]:
    """All files under ``roles/`` that may carry templated YAML, env, or
    configuration content."""
    for s in iter_project_files(exclude_tests=True, exclude_dirs=("docs",)):
        p = Path(s)
        try:
            rel = p.relative_to(ROLES_DIR)
        except ValueError:
            continue
        # Skip binary blobs and docs subtrees inside roles.
        if any(seg in {"docs", "files"} for seg in rel.parts[:-1]):
            continue
        yield p


class TestDomainPrimarySpot(unittest.TestCase):
    """Subdomain-of-DOMAIN_PRIMARY literals MUST stay in canonical/aliases."""

    def test_only_canonical_or_aliases_use_domain_primary(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for path in _scan_paths():
            issues = _file_offenders(path)
            if issues:
                offenders[path] = issues

        if not offenders:
            return

        rel = lambda p: p.relative_to(PROJECT_ROOT)  # noqa: E731
        lines = [
            f"{len(offenders)} file(s) construct a hostname via "
            f"`<sub>.{{{{ DOMAIN_PRIMARY }}}}` outside of the role's "
            f"canonical/aliases SPOT:",
        ]
        for path, issues in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            lines.extend(f"      * {issue}" for issue in issues)
        lines.append("")
        lines.append(
            "Fix: replace the literal with `\"{{ lookup('domain', "
            "'<role>') }}\"` (or `\"{{ lookup('tls', '<role>', 'url.base') "
            '}}"` when the full URL is needed). Define the canonical '
            "hostname only in the owning role's `meta/domains.yml` "
            "`canonical` / `aliases` block."
        )
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
