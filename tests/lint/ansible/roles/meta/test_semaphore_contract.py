"""Lint: every invokable role declares how Semaphore controls it.

The contract lives in ``meta/services.yml``. Every invokable role declares::

    semaphore:
      enabled: "{{ 'web-app-semaphore' in group_names }}"
      shared: "{{ 'web-app-semaphore' in group_names }}"
      control: true
      status: started

``control`` is a literal boolean; ``true`` puts the role under Semaphore's stop
and start templates. ``status`` is ``started`` or ``stopped``, the state a
deploy creates the role in.

A custom role pulled into ``roles/web-app-cst-*`` is invokable and is scanned
like an in-tree role. It declares the entry in the ``meta/services.yml`` of its
source repository; the missing-entry finding prints the block to append.

Findings
--------

* the role's ``meta/services.yml`` has no ``semaphore`` mapping, or the mapping
  lacks one of ``enabled``, ``shared``, ``control`` and ``status``;
* ``enabled`` or ``shared`` is not the expression above;
* ``control`` is not a literal boolean;
* ``status`` is neither ``started`` nor ``stopped``;
* ``control: false`` states no reason;
* a role of ``CONTROL_PLANE`` is under control, is created stopped, or (apart
  from ``web-app-semaphore``, whose entry is its own container) registers with
  Semaphore at all.

Suppression
-----------

``# nocheck: semaphore-contract`` followed by a reason of at least
``MIN_REASON_CHARS`` characters. On the ``semaphore:`` line or in the comment
block directly above it, the marker covers the whole entry; on a field's line or
in the comment block directly above that field, it covers that field. A bare
marker grants nothing. A missing entry or key and the control-plane rules
cannot be suppressed.
"""

from __future__ import annotations

import re
import textwrap
import unittest
from collections.abc import Mapping

import yaml

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.required_by_coverage import role_is_invokable

from . import role_dirs

RULE = "semaphore-contract"
KEY = "semaphore"
SELF_ROLE = "web-app-semaphore"
FLAG = "{{ 'web-app-semaphore' in group_names }}"
FIELDS = ("enabled", "shared", "control", "status")
STATUSES = ("started", "stopped")
CONTROL_PLANE = (
    SELF_ROLE,
    "web-app-keycloak",
    "svc-db-postgres",
    "svc-db-openldap",
    "svc-prx-openresty",
    "web-app-gitea",
)
MIN_REASON_CHARS = 10
CONSUMER_MARKER = (
    "# nocheck: bond-baseline, variants-coverage  Semaphore controls the "
    "role from outside the variant topology and no task of the role "
    "branches on this flag, so no variant round has a polarity to exercise"
)
ENTRY = "\n".join(
    (
        CONSUMER_MARKER,
        f"{KEY}:",
        "  bond: 0.5",
        f'  enabled: "{FLAG}"',
        f'  shared: "{FLAG}"',
        "  control: true",
        "  status: started",
    )
)
DECLARE_HINT = (
    "append this block to the role's own `meta/services.yml`; a custom "
    "`roles/web-app-cst-*` role carries it in its source repository at "
    "`source.path`, because every pull replaces the placed directory. Where "
    f"Semaphore must not pause the role, declare `control: false # nocheck: {RULE}` "
    "with the reason:\n" + textwrap.indent(ENTRY, "      ")
)

_KEY_LINE = re.compile(rf"^{KEY}\s*:")
_TOP_LEVEL = re.compile(r"^[^\s#]")
_MARKER = re.compile(
    r"(?:noqa|nocheck)\s*:\s*"
    r"[a-z0-9][a-z0-9\-]*(?:\s*,\s*[a-z0-9][a-z0-9\-]*)*(.*)$",
    re.IGNORECASE,
)


def entry_span(lines: list[str]) -> range | None:
    """The 1-based line numbers of the ``semaphore:`` key line and its body.

    Args:
        lines: the services file's lines.

    Returns:
        The span, or None when no top-level ``semaphore:`` line exists.
    """
    start = next(
        (n for n, line in enumerate(lines, 1) if _KEY_LINE.match(line)),
        None,
    )
    if start is None:
        return None
    end = next(
        (n for n in range(start + 1, len(lines) + 1) if _TOP_LEVEL.match(lines[n - 1])),
        len(lines) + 1,
    )
    return range(start, end)


def _reason(line: str) -> str | None:
    """The reason a ``semaphore-contract`` marker on *line* gives.

    Args:
        line: one line of the services file.

    Returns:
        The text after the marker's rule list, or None without the marker.
    """
    if not line_has_rule(line, RULE):
        return None
    match = _MARKER.search(line)
    return match.group(1).strip().lstrip("-:—").strip() if match else ""


def _justified(lines: list[str], number: int | None) -> bool:
    """Whether line *number* or the comment block above it gives a reason.

    Args:
        lines: the services file's lines.
        number: 1-based line of the construct, None when it has no line.
    """
    if number is None:
        return False
    candidates = [number - 1]
    scan = number - 2
    while scan >= 0 and lines[scan].lstrip().startswith("#"):
        candidates.append(scan)
        scan -= 1
    reasons = (_reason(lines[index]) for index in candidates)
    return any(r is not None and len(r) >= MIN_REASON_CHARS for r in reasons)


def _field_line(lines: list[str], span: range, field: str) -> int | None:
    """The 1-based line declaring *field* directly under ``semaphore:``.

    Args:
        lines: the services file's lines.
        span: the entry's span from :func:`entry_span`.
        field: the child key to locate.
    """
    body = [
        n
        for n in span[1:]
        if lines[n - 1].strip() and not lines[n - 1].lstrip().startswith("#")
    ]
    if not body:
        return None
    first = lines[body[0] - 1]
    indent = first[: len(first) - len(first.lstrip())]
    pattern = re.compile(rf"^{re.escape(indent)}{field}\s*:")
    return next((n for n in body if pattern.match(lines[n - 1])), None)


def _control_plane_findings(role: str, entry: Mapping, where: str) -> list[str]:
    """The rules that keep a control-plane role out of Semaphore's reach.

    Args:
        role: the role the entry belongs to.
        entry: its ``semaphore`` mapping.
        where: the file prefix every message starts with.
    """
    if role not in CONTROL_PLANE:
        return []
    findings: list[str] = []
    if entry.get("control") is not False:
        findings.append(f"{where}: control-plane role must declare `control: false`")
    if entry.get("status") != "started":
        findings.append(f"{where}: control-plane role must declare `status: started`")
    if role != SELF_ROLE and entry.get("enabled") is not False:
        findings.append(f"{where}: control-plane role must declare `enabled: false`")
    return findings


def entry_findings(role: str, text: str) -> list[str]:
    """Contract findings for one role's ``meta/services.yml``.

    Args:
        role: the role the file belongs to, named in every finding.
        text: the file's content; empty when the role ships no such file.

    Returns:
        One message per violation, empty when the role keeps the contract.
    """
    where = f"roles/{role}/{ROLE_FILE_META_SERVICES}"
    try:
        services = load_yaml_str(text) if text.strip() else None
    except yaml.YAMLError as exc:
        return [f"{where}: does not parse: {exc}"]
    entry = services.get(KEY) if isinstance(services, Mapping) else None
    lines = text.splitlines()
    span = entry_span(lines)
    if not isinstance(entry, Mapping) or span is None:
        return [
            f"{where}: lacks the `{KEY}` entry ({', '.join(FIELDS)}); {DECLARE_HINT}"
        ]

    def justified(field: str) -> bool:
        return _justified(lines, span.start) or _justified(
            lines, _field_line(lines, span, field)
        )

    hint = f"or add `# nocheck: {RULE}` with a reason"
    findings = [
        f"{where}: `{KEY}` lacks `{field}`" for field in FIELDS if field not in entry
    ]
    findings.extend(
        f"{where}: {KEY}.{flag} is {entry[flag]!r}, expected {FLAG!r} {hint}"
        for flag in ("enabled", "shared")
        if flag in entry and entry[flag] != FLAG and not justified(flag)
    )
    control = entry.get("control")
    if (
        "control" in entry
        and not isinstance(control, bool)
        and not justified("control")
    ):
        findings.append(
            f"{where}: {KEY}.control is {control!r}, not a literal boolean {hint}"
        )
    if control is False and not justified("control"):
        findings.append(
            f"{where}: {KEY}.control is false without a reason; add "
            f"`# nocheck: {RULE}` naming why Semaphore must not pause the role"
        )
    status = entry.get("status")
    if "status" in entry and status not in STATUSES and not justified("status"):
        findings.append(
            f"{where}: {KEY}.status is {status!r}, expected one of "
            f"{', '.join(STATUSES)} {hint}"
        )
    findings.extend(_control_plane_findings(role, entry, where))
    return findings


def offenders() -> list[str]:
    """Every contract finding across the invokable roles."""
    findings: list[str] = []
    for role_dir in role_dirs():
        if not role_is_invokable(role_dir.name):
            continue
        path = role_dir / ROLE_FILE_META_SERVICES
        text = read_text(str(path)) if path.is_file() else ""
        findings.extend(entry_findings(role_dir.name, text))
    return findings


class TestSemaphoreContract(unittest.TestCase):
    def test_every_invokable_role_declares_the_contract(self) -> None:
        findings = offenders()
        self.assertEqual(
            [],
            findings,
            f"Semaphore contract violations ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_every_control_plane_role_exists(self) -> None:
        known = {role_dir.name for role_dir in role_dirs()}
        self.assertEqual(
            [],
            [role for role in CONTROL_PLANE if role not in known],
            "CONTROL_PLANE names a role that no longer exists; follow the rename",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
