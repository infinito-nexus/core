"""Lint: forbid Ansible constructs that emit [DEPRECATION WARNING] at deploy.

Each pattern below triggered a deprecation in CI and has a non-deprecated
replacement. Keeping them out of the tree means the compose deploy's
deprecation gate (assert_no_deprecation_warnings.sh) stays green.

Forbidden (with fix):

* ``ansible.builtin.apt_repository`` / ``apt_repository:`` -- deprecated module.
  Write the ``.list`` via ``ansible.builtin.copy`` (the repo's apt_repo.sh keeps
  the canonical .list and deletes .sources, so deb822_repository is unusable
  here) plus an explicit ``apt: update_cache``.
* ``community.mysql.*`` -- the collection moved to ``ansible.mysql`` (community
  removes it in 6.0.0). Use ``ansible.mysql.<module>`` and keep ``ansible.mysql``
  in requirements/requirements.galaxy.yml.
* top-level injected gathered facts (``ansible_os_family`` and friends) --
  ``INJECT_FACTS_AS_VARS`` default is deprecated. Use ``ansible_facts['<name>']``.
  Only gathered facts are denied; magic/connection vars (ansible_version, host,
  user, connection, python_interpreter, become_*, failed_result, ...) are not
  facts and stay allowed. The ``(?!=)`` guard skips a literal log label such as
  ``ansible_virtualization_type={{ ... }}`` (name glued to ``=``) while still
  flagging a comparison like ``ansible_os_family == 'X'`` (space before ``==``).

Scans ``.yml`` / ``.yaml`` / ``.j2`` under roles/, tasks/, group_vars/. Mark a
genuine exception with ``# nocheck: deprecated-ansible`` same-or-above the line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "deprecated-ansible"
SCAN_SUFFIXES = (".yml", ".yaml", ".j2")
_SCAN_PREFIXES = ("roles/", "tasks/", "group_vars/")

_FACT_NAMES = (
    "os_family",
    "distribution",
    "distribution_release",
    "distribution_version",
    "distribution_major_version",
    "distribution_file_variety",
    "architecture",
    "machine",
    "system",
    "kernel",
    "kernel_version",
    "default_ipv4",
    "default_ipv6",
    "all_ipv4_addresses",
    "all_ipv6_addresses",
    "virtualization_type",
    "virtualization_role",
    "processor",
    "processor_cores",
    "processor_count",
    "processor_vcpus",
    "memtotal_mb",
    "memfree_mb",
    "mounts",
    "devices",
    "interfaces",
    "hostname",
    "nodename",
    "fqdn",
    "domain",
    "pkg_mgr",
    "service_mgr",
    "selinux",
    "date_time",
    "lsb",
    "dns",
)

_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "apt_repository",
        re.compile(r"(?:ansible\.builtin\.)?apt_repository\s*:"),
        "deprecated module -> write the .list via ansible.builtin.copy + apt update_cache",
    ),
    (
        "community.mysql",
        re.compile(r"\bcommunity\.mysql\."),
        "collection renamed -> use ansible.mysql.<module> (add ansible.mysql to galaxy reqs)",
    ),
    (
        "injected-fact",
        re.compile(rf"\bansible_(?:{'|'.join(_FACT_NAMES)})\b(?!=)"),
        "top-level injected fact -> use ansible_facts['<name>']",
    ),
)


def _scan_file(path: Path) -> list[str]:
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.splitlines()
    out: list[str] = []
    for idx, line in enumerate(lines, start=1):
        for kind, pattern, fix in _PATTERNS:
            if pattern.search(line) and not is_suppressed_at(
                lines, idx, _RULE, mode="same-or-above"
            ):
                out.append(f"line {idx}: [{kind}] {line.strip()}  -> {fix}")
    return out


class TestNoDeprecatedAnsiblePatterns(unittest.TestCase):
    def test_no_deprecated_patterns(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for abs_path in iter_project_files(extensions=SCAN_SUFFIXES):
            rel = Path(abs_path).relative_to(PROJECT_ROOT).as_posix()
            if not rel.startswith(_SCAN_PREFIXES):
                continue
            issues = _scan_file(Path(abs_path))
            if issues:
                offenders[Path(abs_path)] = issues

        if offenders:
            lines = [
                f"{sum(len(v) for v in offenders.values())} deprecated Ansible pattern(s):"
            ]
            for path, issues in sorted(offenders.items()):
                lines.append(f"  - {path.relative_to(PROJECT_ROOT)}:")
                lines.extend(f"      * {i}" for i in issues)
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
