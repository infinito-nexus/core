"""Lint: a loopback host list comes from the SPOT, and the SPOT keeps all three forms.

Loopback identity has three spellings a client may send: the IPv4 literal, the
IPv6 literal and the name. A hand-written list almost always carries two and
omits the third, so the exemption or allowlist it builds stops at whichever
form the client actually used. That is how ``no_proxy=localhost,127.0.0.1``
sent an S3 write through a SOCKS proxy while appearing to exempt loopback.

``NETWORK_LOOPBACK_HOSTS`` in ``group_vars/all/08_networks.yml`` is the single
list, so adding a form reaches every consumer at once.

Scope: assignments whose key names a proxy exemption (``no_proxy``) or a host
allowlist (``allowed_hosts``). A deny list mixes CIDRs with names and a
reachability probe takes a resolver argument, so neither is a loopback host
list and neither is flagged.

Per-line opt-out: ``# nocheck: loopback-hosts-literal``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import PROJECT_ROOT, iter_project_files_with_content, read_text

_RULE = "loopback-hosts-literal"
_SPOT_FILE = "group_vars/all/08_networks.yml"
_SPOT_VAR = "NETWORK_LOOPBACK_HOSTS"

_FORMS = {
    "ipv4": re.compile(r"(?<![\d.])127\.0\.0\.1(?![\d.])"),
    "ipv6": re.compile(r"(?<![\w:])::1(?![\w:])"),
    "name": re.compile(r"(?<![\w.-])localhost(?![\w.-])"),
}

_COMMENT = re.compile(r"\s+#.*$")
_HOST_LIST = re.compile(
    r"(?i)^[\s\-]*[\w.]*(?:no_proxy|allowed_hosts)\s*[:=]\s*(?P<value>.+)$"
)
_LOOKUP = "proxy_excluded_hosts"
_INTERNAL_EXCLUSION = re.compile(
    r"^(?P<key>[A-Z][A-Z0-9_]*PROXY[A-Z0-9_]*(?:EXCLUDED|BYPASS)[A-Z0-9_]*)\s*:"
)
_COMPOSITION = re.compile(r"[A-Z][A-Z0-9_]*PROXY[A-Z0-9_]*(?:EXCLUDED|BYPASS)")


def forms_in(text: str) -> set[str]:
    """Return the loopback spellings this text writes as literals.

    Args:
        text: one source line, or the value half of an assignment.
    """
    return {name for name, pattern in _FORMS.items() if pattern.search(text)}


def host_list_value(line: str) -> str | None:
    """Return the value of a proxy-exemption or host-allowlist assignment.

    Args:
        line: one source line; a trailing comment is stripped first, so a
            form named only in prose does not count as a literal.
    """
    match = _HOST_LIST.match(_COMMENT.sub("", line))
    return match.group("value") if match else None


class TestLoopbackHostsSpot(unittest.TestCase):
    def test_no_host_list_enumerates_loopback_forms_itself(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2", ".yml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                value = host_list_value(line)
                if value is None or _SPOT_VAR in value:
                    continue
                if len(forms_in(value)) < 2:
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, idx + 1, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {s}"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found hand-written loopback host lists. Each one fixes which "
                "spellings of loopback are covered, so the form a client "
                "actually sends is the one left out.\n\n"
                f"Fix: render `{_SPOT_VAR}` from {_SPOT_FILE} — "
                "`| join(',')` for an env value, or concatenated with the "
                "role's own hosts.\n\n"
                f"Offending lines:\n{formatted}"
            )

    def test_internal_proxy_exclusions_come_from_the_lookup(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                stripped = _COMMENT.sub("", line).strip()
                match = _INTERNAL_EXCLUSION.match(stripped)
                if not match or "PUBLIC" in match.group("key"):
                    continue
                block = "\n".join(lines[idx : idx + 6])
                if _LOOKUP in block:
                    continue
                value = stripped[len(match.group(0)) :]
                if _COMPOSITION.search(value):
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, idx + 1, match.group("key")))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {k}"
                for p, n, k in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found proxy-exclusion lists that name their internal hosts by "
                "hand. A role exporting a proxy applies it to every HTTP call "
                "the app makes, so an internal dependency left off the list is "
                "proxied and fails.\n\n"
                f"Fix: render `lookup('{_LOOKUP}', application_id)` and "
                "concatenate the role's own extra hosts. A list of public "
                "hosts belongs in a separate `..._PUBLIC_...` variable.\n\n"
                f"Offending variables:\n{formatted}"
            )

    def test_the_scan_detects_host_lists_and_not_their_near_misses(self) -> None:
        caught = (
            "no_proxy=localhost,127.0.0.1",
            'lab_no_proxy: "localhost,127.0.0.1,::1,other"',
            "ALLOWED_HOSTS={{ H }},127.0.0.1,localhost",
            "PRETIX_PRETIX_ALLOWED_HOSTS={{ H }},127.0.0.1,localhost",
        )
        for line in caught:
            with self.subTest(caught=line):
                value = host_list_value(line)
                self.assertIsNotNone(value)
                self.assertGreaterEqual(len(forms_in(value)), 2)

        ignored = (
            'DOCKER_REACH_HOST: "127.0.0.1" # Default localhost, overwritten later',
            "HTTP_DENY_LIST=0.0.0.0,127.0.0.0/8,::1,localhost,ip6-localhost",
            "'drill -p 53 localhost @127.0.0.1 >/dev/null 2>&1'",
            "no_proxy={{ NETWORK_LOOPBACK_HOSTS | join(',') }}",
        )
        for line in ignored:
            with self.subTest(ignored=line):
                value = host_list_value(line)
                self.assertTrue(
                    value is None or _SPOT_VAR in value or len(forms_in(value)) < 2,
                    f"should not be flagged: {line}",
                )

        self.assertEqual(
            {"ipv4", "ipv6", "name"},
            forms_in("127.0.0.1 ::1 localhost"),
            "every form must be detectable, or the rule passes vacuously",
        )

    def test_the_exclusion_scan_separates_enumeration_from_composition(self) -> None:
        enumerating = 'ROLE_PROXY_EXCLUDED_INTERNAL_HOSTS: ["db", "cache"]'
        match = _INTERNAL_EXCLUSION.match(enumerating)
        self.assertIsNotNone(match, "an internal exclusion list must be recognised")
        self.assertNotIn("PUBLIC", match.group("key"))
        value = enumerating[len(match.group(0)) :]
        self.assertIsNone(
            _COMPOSITION.search(value),
            "a hand-written list must not look like a composition",
        )

        composed = (
            "ROLE_PROXY_EXCLUDED_HOSTS: "
            '"{{ ROLE_PROXY_EXCLUDED_PUBLIC_HOSTS + ROLE_PROXY_EXCLUDED_INTERNAL_HOSTS }}"'
        )
        composed_match = _INTERNAL_EXCLUSION.match(composed)
        self.assertIsNotNone(composed_match)
        self.assertIsNotNone(
            _COMPOSITION.search(composed[len(composed_match.group(0)) :]),
            "a concatenation of other exclusion vars must count as composition",
        )

        public = 'ROLE_PROXY_EXCLUDED_PUBLIC_HOSTS: ["github.com"]'
        public_match = _INTERNAL_EXCLUSION.match(public)
        self.assertIsNotNone(public_match)
        self.assertIn(
            "PUBLIC",
            public_match.group("key"),
            "a public host list must be exempt; it names no internal service",
        )

    def test_the_spot_covers_every_loopback_form(self) -> None:
        spot = read_text(str(PROJECT_ROOT / _SPOT_FILE))
        declared = [
            line for line in spot.splitlines() if line.startswith(f"{_SPOT_VAR}:")
        ]
        self.assertEqual(
            1,
            len(declared),
            f"{_SPOT_FILE} must declare {_SPOT_VAR} exactly once, found "
            f"{len(declared)}",
        )
        missing = sorted(
            name
            for name in _FORMS
            if f"NETWORK_LOOPBACK_{name.upper()}" not in declared[0]
        )
        self.assertEqual(
            [],
            missing,
            f"{_SPOT_VAR} must reference every loopback form so no consumer "
            f"narrows silently; missing: {missing}",
        )
