"""Lint: every role ``env.j2`` includes the shared container env base and
never re-sets a key the base owns.

``roles/sys-svc-container/templates/env.j2`` is the shared base included at
the top of every role's ``templates/env.j2``. It is rendered by
``sys-svc-compose`` ``04_files.yml`` through ``stack_host_template`` -- the
same engine that resolves ``{% include 'roles/...' %}`` in ``compose.yml.j2``
-- so the include works in ``env.j2`` too. The base sets the container-wide
defaults (``TZ``, ``LANG``).

Every role ``env.j2`` MUST:

1. include the base::

       {% include 'roles/sys-svc-container/templates/env.j2' %}

2. NOT re-set a key the base owns (``TZ``, ``LANG``) -- those come from the
   base only, so each value stays single-source.

The owned keys are derived from the base file itself (SPOT): add a ``KEY=``
line to the base and it is automatically enforced here.

Scope: ``roles/*/templates/env.j2`` (exact name), excluding the base itself.

Suppress a genuine exception with ``# nocheck: env-base-include`` or
``# nocheck: env-base-duplicate-key`` on (or above) the offending line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_BASE_REL = "roles/sys-svc-container/templates/env.j2"
_INCLUDE_RULE = "env-base-include"
_DUP_RULE = "env-base-duplicate-key"

_INCLUDE_RE = re.compile(
    r"\{%-?\s*include\s+['\"]" + re.escape(_BASE_REL) + r"['\"]\s*-?%\}"
)
_ASSIGN_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=")


def _base_owned_keys() -> list[str]:
    base = PROJECT_ROOT / _BASE_REL
    keys: list[str] = []
    for line in read_text(str(base)).splitlines():
        m = _ASSIGN_RE.match(line)
        if m:
            keys.append(m.group("key"))
    return keys


def _candidate_paths() -> list[Path]:
    base_abs = (PROJECT_ROOT / _BASE_REL).resolve()
    out: list[Path] = []
    for s in iter_project_files(extensions=(".j2",)):
        p = Path(s)
        if p.name != "env.j2":
            continue
        try:
            rel = p.relative_to(PROJECT_ROOT)
        except ValueError:
            continue
        parts = rel.parts
        if len(parts) != 4 or parts[0] != "roles" or parts[2] != "templates":
            continue
        if p.resolve() == base_abs:
            continue
        out.append(p)
    return out


class TestEnvBaseInclude(unittest.TestCase):
    def test_env_files_include_base(self) -> None:
        offenders: list[str] = []
        for path in _candidate_paths():
            try:
                text = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            if _INCLUDE_RE.search(text):
                continue
            lines = text.splitlines()
            if any(f"nocheck: {_INCLUDE_RULE}" in line for line in lines):
                continue
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

        if offenders:
            report = [
                f"{len(offenders)} role env.j2 file(s) do not include the shared "
                "container env base.",
                f"  Fix: add `{{% include '{_BASE_REL}' %}}` at the top of the file.",
                f"  Suppress a genuine exception with `# nocheck: {_INCLUDE_RULE}`.",
            ]
            report.extend(f"  - {o}" for o in sorted(offenders))
            self.fail("\n".join(report))

    def test_env_files_do_not_reset_base_keys(self) -> None:
        owned = _base_owned_keys()
        self.assertTrue(owned, f"base {_BASE_REL} defines no KEY= lines")
        key_re = re.compile(r"^\s*(?P<key>" + "|".join(owned) + r")\s*=")

        offenders: dict[str, list[str]] = {}
        for path in _candidate_paths():
            try:
                text = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            lines = text.splitlines()
            hits: list[str] = []
            for line_no, line in enumerate(lines, start=1):
                m = key_re.match(line)
                if not m:
                    continue
                if is_suppressed_at(lines, line_no, _DUP_RULE, mode="same-or-above"):
                    continue
                hits.append(f"line {line_no}: {m.group('key')}")
            if hits:
                offenders[str(path.relative_to(PROJECT_ROOT))] = hits

        if offenders:
            report = [
                f"{sum(len(v) for v in offenders.values())} role env.j2 line(s) "
                f"re-set a base-owned key ({', '.join(owned)}). These come from "
                f"{_BASE_REL} only.",
                "  Fix: delete the line; the base supplies the value.",
                f"  Suppress a genuine exception with `# nocheck: {_DUP_RULE}`.",
            ]
            for path, hits in sorted(offenders.items()):
                report.append(f"  - {path}:")
                report.extend(f"      * {h}" for h in hits)
            self.fail("\n".join(report))


if __name__ == "__main__":
    unittest.main()
