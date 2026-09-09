"""A ``healthcheck`` timing in ``meta/services.yml`` either matches its flavor's
default and should be gone, or differs and must say why.

``utils/docker/healthcheck`` owns the five timings. ``Probe`` holds the platform
defaults, every flavor may raise its own (``Curl`` probes every minute,
``Connect`` grants a fifteen minute start window), and a prefix raises them
further. The lookup then writes ``overrides.get(key, effective_default)``, so a
service that repeats what it would have inherited changes nothing and only hides
the moment the default moves.

A value that differs is a decision, and one that costs something carries a
reason rather than a number alone. Three do: ``interval`` is steady state load
for the life of the deployment, ``timeout`` decides when a slow probe counts as
a failure, and ``start_interval`` is the only timing that moves the moment a
stack reports healthy. ``start_period`` and ``retries`` buy patience with a
broken container and cost nothing while it works, so a deviation there needs no
defence and only the redundant restatement is flagged.

Comparison is against the EFFECTIVE default, resolved through the same
``compose`` the lookup uses. Comparing against ``Probe`` alone would flag every
service that simply agrees with its flavor.

A definition that does NOT go through the lookup inherits nothing from the SPOT.
Docker has no daemon-wide healthcheck default to fall back on: ``daemon.json``
carries storage, logging, DNS, registries and runtimes, and no ``health-*`` key
at all. An omitted timing therefore lands on DOCKER's default, not the
platform's, and the two disagree where it matters most, ``start_period`` being
zero rather than thirty seconds, which leaves ``start_interval`` no window to
act in. So a literal ``healthcheck:`` block in a template, and a ``HEALTHCHECK``
line in a role's own Dockerfile, must spell every timing out at the platform
value.

Per-key opt-out
===============
``# nocheck: healthcheck-timing-override`` on the timing line or the one above
it, with a short reason. The reason is the point: a bare marker restates the
number the reader can already see. For a value a literal definition leaves out
entirely, put the marker on the ``healthcheck:`` or ``HEALTHCHECK`` line, which
is the only line the omission has.
"""

from __future__ import annotations

import contextlib
import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml_any
from utils.docker.healthcheck.compose import compose
from utils.docker.healthcheck.probes import TIMING_DEFAULTS
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

RULE = "healthcheck-timing-override"

DOCUMENTED_KEYS = ("interval", "timeout", "start_interval")


def _effective_defaults(flavor: object) -> dict[str, object]:
    """The timings a service inherits when it declares none.

    Args:
        flavor: the ``healthcheck.flavor`` value, empty for an explicit test.
    """
    if not flavor:
        return dict(TIMING_DEFAULTS)
    with contextlib.suppress(Exception):
        probe = compose(flavor)  # type: ignore[arg-type]
        return {key: getattr(probe, key) for key in TIMING_DEFAULTS}
    return dict(TIMING_DEFAULTS)


def _timing_line(lines: list[str], service: str, key: str) -> int | None:
    """1-based line of ``key`` inside *service*'s healthcheck block."""
    in_service = False
    in_health = False
    for index, line in enumerate(lines, start=1):
        if re.match(rf"^{re.escape(service)}\s*:", line):
            in_service, in_health = True, False
            continue
        if in_service and re.match(r"^\S", line):
            return None
        if in_service and re.match(r"^\s+healthcheck\s*:", line):
            in_health = True
            continue
        if in_health and re.match(r"^\s{0,2}\S", line):
            in_health = False
        if in_health and re.match(rf"^\s+{re.escape(key)}\s*:", line):
            return index
    return None


def timing_findings() -> tuple[list[str], list[str]]:
    """Return ``(redundant, undocumented)`` findings as printable lines."""
    redundant: list[str] = []
    undocumented: list[str] = []
    for meta in sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")):
        try:
            content = read_text(str(meta))
            data = load_yaml_any(str(meta), default_if_missing={}) or {}
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        lines = content.splitlines()
        rel = meta.relative_to(PROJECT_ROOT).as_posix()
        for service, entry in data.items():
            if not isinstance(entry, dict):
                continue
            health = entry.get("healthcheck")
            if not isinstance(health, dict):
                continue
            defaults = _effective_defaults(health.get("flavor"))
            for key, default in defaults.items():
                if key not in health:
                    continue
                line_no = _timing_line(lines, service, key)
                where = f"{rel}:{line_no or '?'} {service}.{key}"
                if str(health[key]) == str(default):
                    redundant.append(f"{where} = {health[key]} (the default)")
                elif key in DOCUMENTED_KEYS and (
                    line_no is None or not is_suppressed_at(lines, line_no, RULE)
                ):
                    undocumented.append(f"{where} = {health[key]}, default {default}")
    return redundant, undocumented


_YAML_KEY = "healthcheck:"
_DOCKERFILE_KEY = "HEALTHCHECK"
_DOCKERFILE_FLAG = "--{key}="


def _yaml_literal_timings(lines: list[str], index: int) -> dict[str, tuple[str, int]]:
    """Timings declared under the ``healthcheck:`` at *index*, with their lines."""
    indent = len(lines[index]) - len(lines[index].lstrip())
    found: dict[str, tuple[str, int]] = {}
    for offset, line in enumerate(lines[index + 1 :], start=index + 2):
        if not line.strip():
            break
        if len(line) - len(line.lstrip()) <= indent:
            break
        for key in TIMING_DEFAULTS:
            match = re.match(rf"^\s+{key}\s*:\s*(.+?)\s*(?:#.*)?$", line)
            if match:
                found[key] = (match.group(1), offset - 1)
    return found


def _dockerfile_timings(lines: list[str], index: int) -> dict[str, tuple[str, int]]:
    """Timings on the ``HEALTHCHECK`` at *index*, following its continuations."""
    found: dict[str, tuple[str, int]] = {}
    cursor = index
    while cursor < len(lines):
        for key in TIMING_DEFAULTS:
            flag = _DOCKERFILE_FLAG.format(key=key.replace("_", "-"))
            match = re.search(rf"{re.escape(flag)}(\S+)", lines[cursor])
            if match:
                found[key] = (match.group(1), cursor + 1)
        if not lines[cursor].rstrip().endswith("\\"):
            break
        cursor += 1
    return found


def literal_findings() -> list[str]:
    """Timings a non-lookup definition gets wrong, omits, or leaves unexplained."""
    findings: list[str] = []
    for path_str, content in iter_project_files_with_content(exclude_tests=True):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if not rel.startswith("roles/"):
            continue
        is_dockerfile = Path(rel).name.startswith("Dockerfile")
        if not (rel.endswith(".j2") or is_dockerfile):
            continue
        lines = content.splitlines()
        for index, line in enumerate(lines):
            if is_dockerfile:
                if not line.lstrip().startswith(_DOCKERFILE_KEY):
                    continue
                declared = _dockerfile_timings(lines, index)
            else:
                if line.strip() != _YAML_KEY:
                    continue
                declared = _yaml_literal_timings(lines, index)
                if not declared and "{{" not in content:
                    continue
            anchor = index + 1
            for key, default in TIMING_DEFAULTS.items():
                value, line_no = declared.get(key, (None, anchor))
                if value is not None and str(value) == str(default):
                    continue
                if value is not None and key not in DOCUMENTED_KEYS:
                    continue
                if is_suppressed_at(lines, line_no, RULE):
                    continue
                shown = "omitted" if value is None else value
                findings.append(f"{rel}:{line_no} {key} = {shown}, default {default}")
    return findings


class TestHealthcheckTimingOverrides(unittest.TestCase):
    def test_no_timing_restates_its_default(self) -> None:
        redundant, _ = timing_findings()
        if not redundant:
            return
        self.fail(
            "These healthcheck timings repeat the value their flavor already "
            "gives them. They change nothing and hide the day the default "
            "moves, so delete the line.\n\n" + "\n".join(f"- {f}" for f in redundant)
        )

    def test_every_deviating_timing_says_why(self) -> None:
        _, undocumented = timing_findings()
        if not undocumented:
            return
        self.fail(
            "These healthcheck timings differ from their flavor's default "
            "without saying why. A number alone outlives the reason for it.\n\n"
            "Fix: put the reason on the timing line or the one above it:\n\n"
            f"    # nocheck: {RULE}  <why this service needs another value>\n\n"
            + "\n".join(f"- {f}" for f in undocumented)
        )


    def test_definitions_outside_the_lookup_spell_the_defaults_out(self) -> None:
        findings = literal_findings()
        if not findings:
            return
        self.fail(
            "These healthcheck definitions bypass the lookup, so they inherit "
            "nothing from the SPOT. Docker has no daemon-wide default to fall "
            "back on, and an omitted timing lands on docker's value rather than "
            "the platform's.\n\n"
            "Fix: spell the timing out at the platform value, or say why this "
            "definition needs another one:\n\n"
            f"    # nocheck: {RULE}  <why>\n\n" + "\n".join(f"- {f}" for f in findings)
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
