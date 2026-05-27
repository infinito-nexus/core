"""Lint guard: never hard-code an IP that lives in
``NETWORK_PUBLIC_DNS_RESOLVERS``. Roles, playbooks, scripts and
templates MUST consume the variable so a single edit in
``group_vars/all/08_networks.yml`` propagates everywhere.

Per-line opt-out via ``# nocheck: hardcoded-dns-resolver`` (or
``# nocheck: hardcoded-dns-resolver``) is allowed for files where the
literal IP is genuinely required at the substitution point — CoreDNS
``forward`` directives that don't run through Jinja, host-bootstrap
shell scripts, documentation examples, etc.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text
from utils.cache.yaml import load_yaml_any

_NETWORKS_FILE = PROJECT_ROOT / "group_vars" / "all" / "08_networks.yml"

_SCAN_EXTENSIONS = (
    ".yml",
    ".yaml",
    ".j2",
    ".jinja",
    ".jinja2",
    ".tmpl",
    ".conf",
    ".py",
    ".sh",
    ".md",
)

# Files outside `iter_project_files`'s reach we still want covered.
_EXTRA_PATHS = (PROJECT_ROOT / "compose" / "coredns" / "Corefile.tmpl",)


def _load_resolver_ips() -> list[str]:
    data = load_yaml_any(str(_NETWORKS_FILE)) or {}
    resolvers = data.get("NETWORK_PUBLIC_DNS_RESOLVERS")
    if not isinstance(resolvers, list):
        raise TypeError(
            f"NETWORK_PUBLIC_DNS_RESOLVERS missing or non-list in {_NETWORKS_FILE}"
        )
    out: list[str] = []
    out.extend(
        item.strip() for item in resolvers if isinstance(item, str) and item.strip()
    )
    if not out:
        raise AssertionError(
            f"NETWORK_PUBLIC_DNS_RESOLVERS is empty in {_NETWORKS_FILE}"
        )
    return out


def _build_pattern(ips: list[str]) -> re.Pattern[str]:
    escaped = "|".join(re.escape(ip) for ip in ips)
    # \D|^ before, \D|$ after — IP must stand alone (no longer numeric run).
    return re.compile(rf"(?<![0-9\.])({escaped})(?![0-9\.])")


def _candidate_paths():
    seen: set[Path] = set()
    for s in iter_project_files():
        p = Path(s)
        if p.suffix.lower() not in _SCAN_EXTENSIONS:
            continue
        seen.add(p)
        yield p
    for extra in _EXTRA_PATHS:
        if extra.is_file() and extra not in seen:
            yield extra


class TestNoHardcodedDnsResolvers(unittest.TestCase):
    def test_resolver_ips_only_appear_in_the_central_variable(self) -> None:
        ips = _load_resolver_ips()
        pattern = _build_pattern(ips)
        rule = "hardcoded-dns-resolver"

        offenders: list[str] = []
        for path in _candidate_paths():
            try:
                text = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            if not pattern.search(text):
                continue
            lines = text.splitlines()
            for idx, line in enumerate(lines, start=1):
                if not pattern.search(line):
                    continue
                if is_suppressed_at(lines, idx, rule):
                    continue
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{idx}: {line.strip()}"
                )

        if offenders:
            self.fail(
                "Hard-coded public DNS resolver IPs detected. Use "
                "`NETWORK_PUBLIC_DNS_RESOLVERS` from "
                "`group_vars/all/08_networks.yml` and iterate over it, "
                "or annotate the line with "
                "`# nocheck: hardcoded-dns-resolver` if the literal IP is "
                "genuinely required at that substitution point:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
