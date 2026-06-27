"""Enforce the Compose network-attachment convention.

Each role's ``templates/compose.yml.j2`` MUST attach networks via the shared
lookup plugins so the shared LDAP/DB/Ollama/Proxy networks stay consistent
across every role:

* Per service block ->
  ``{{ lookup('container_networks') | indent(4) }}`` (or matching indent)
* Once at the end (top-level ``networks:`` block) ->
  ``{{ lookup('compose_networks') }}``

Writing a literal ``networks:`` mapping key by hand is forbidden -- the
lookups already derive the correct network name from the service registry
and the role's ``server.networks.overlay`` metadata. The rule applies to
ANY ``*.yml.j2`` under ``roles/*/templates/`` because compose.yml.j2 often
``{% include %}``-pulls service definitions from sibling templates. The
legacy ``{% include 'roles/sys-svc-{compose,container}/templates/networks.yml.j2' %}``
form is also forbidden -- the underlying Jinja templates were replaced by
the lookup plugins.

Genuine exceptions (e.g. local-DB sidecars whose only attachment is
``- default``) declare a ``# nocheck: networks-literal`` marker on the
``networks:`` line itself.

Templates whose only service uses host networking (``network_mode: host``)
are exempt from the top-level lookup requirement because no Docker
``networks:`` block applies in that case.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

NETWORKS_KEY_RE = re.compile(r"^[ \t]*networks\s*:")
NETWORK_MODE_RE = re.compile(r"^[ \t]*network_mode\s*:")
JINJA_TAG_RE = re.compile(r"^\s*\{%")
COMMENT_RE = re.compile(r"^\s*#")
BLANK_RE = re.compile(r"^\s*$")
NOCHECK_RE = re.compile(r"#\s*nocheck:\s*networks-literal\b")

CONTAINER_LOOKUP = "{{ lookup('container_networks') | indent(4) }}"
COMPOSE_LOOKUP = "{{ lookup('compose_networks') }}"
LEGACY_INCLUDE_RE = re.compile(
    r"\{%\s*include\s+['\"]roles/sys-svc-(?:compose|container)"
    r"/templates/networks\.yml\.j2['\"]\s*%\}"
)


def _scan_literals(path) -> list[int]:
    text = read_text(str(path))
    offenders: list[int] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if BLANK_RE.match(line) or COMMENT_RE.match(line):
            continue
        if JINJA_TAG_RE.match(line):
            continue
        if not NETWORKS_KEY_RE.match(line):
            continue
        if NOCHECK_RE.search(line):
            continue
        offenders.append(idx)
    return offenders


def _scan_legacy_includes(path) -> list[int]:
    text = read_text(str(path))
    offenders: list[int] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if LEGACY_INCLUDE_RE.search(line):
            offenders.append(idx)
    return offenders


def _scan_compose_lookup_count(path) -> tuple[int, bool]:
    text = read_text(str(path))
    compose_count = 0
    has_network_mode = False
    for line in text.splitlines():
        if NETWORK_MODE_RE.match(line):
            has_network_mode = True
        if COMPOSE_LOOKUP in line:
            compose_count += 1
    return compose_count, has_network_mode


def _all_role_template_yml_j2() -> list:
    return sorted((PROJECT_ROOT / "roles").glob("*/templates/**/*.yml.j2"))


def _compose_templates() -> list:
    return sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_TEMPL_COMPOSE}"))


class TestComposeNetworkLookups(unittest.TestCase):
    def test_no_literal_networks_key_in_any_compose_template(self) -> None:
        """Detect literal `networks:` in any *.yml.j2 under roles/*/templates/.

        Compose.yml.j2 often includes sibling templates, so the literal
        rule applies to the entire tree, not only the canonical entry
        file. Use `# nocheck: networks-literal` on the offending line to
        declare a deliberate exception.
        """
        offenders: list[str] = []
        for path in _all_role_template_yml_j2():
            lines = _scan_literals(path)
            if lines:
                rel = path.relative_to(PROJECT_ROOT)
                joined = ", ".join(str(n) for n in lines)
                offenders.append(f"- {rel} (line(s) {joined})")

        if offenders:
            self.fail(
                "Templates contain a literal `networks:` mapping key.\n"
                "Each service block MUST attach networks via\n"
                f"  {CONTAINER_LOOKUP}\n"
                "and the top-level `networks:` block MUST be rendered via\n"
                f"  {COMPOSE_LOOKUP}\n"
                "Declare deliberate exceptions with `# nocheck: networks-literal`.\n"
                "Offenders:\n" + "\n".join(offenders)
            )

    def test_no_legacy_networks_include(self) -> None:
        offenders: list[str] = []
        for path in _all_role_template_yml_j2():
            lines = _scan_legacy_includes(path)
            if lines:
                rel = path.relative_to(PROJECT_ROOT)
                joined = ", ".join(str(n) for n in lines)
                offenders.append(f"- {rel} (line(s) {joined})")

        if offenders:
            self.fail(
                "Templates still use the legacy include form. Replace\n"
                "  {% include 'roles/sys-svc-compose/templates/networks.yml.j2' %}\n"
                "  -> "
                f"{COMPOSE_LOOKUP}\n"
                "  {% include 'roles/sys-svc-container/templates/networks.yml.j2' %}\n"
                "  -> "
                f"{CONTAINER_LOOKUP}\n"
                "Offenders:\n" + "\n".join(offenders)
            )

    def test_top_level_compose_networks_lookup_present_once(self) -> None:
        offenders: list[str] = []
        for path in _compose_templates():
            compose_count, host_mode = _scan_compose_lookup_count(path)
            if host_mode and compose_count == 0:
                continue
            if compose_count != 1:
                rel = path.relative_to(PROJECT_ROOT)
                offenders.append(
                    f"- {rel} (found {compose_count} lookup(s); expected exactly 1)"
                )

        if offenders:
            self.fail(
                "Each compose.yml.j2 MUST contain exactly one\n"
                f"  {COMPOSE_LOOKUP}\n"
                "to render the top-level `networks:` block (templates whose\n"
                "only service uses `network_mode:` are exempt). Offenders:\n"
                + "\n".join(offenders)
            )


if __name__ == "__main__":
    unittest.main()
