"""Lint: a once-rendered allowlist names every network sibling of its hosts.

A role template rendered outside the vhost loop cannot know which network
sibling will be asked, so a value that lists the hosts a peer accepts
(Collabora ``aliasgroupN=``, Keycloak ``redirectUris``, ``webOrigins`` and
``post.logout.redirect.uris``, ``trusted_domains``) MUST be the union of every
sibling. A sink line passes when its value, or a variable it reads (resolved
through ``{% set %}`` in the same file and the role's ``vars/main.yml``),
derives its hosts from ``network_urls``, ``network_siblings`` or
``redirect_uris``, or when it holds no host lookup at all. See
``docs/contributing/design/network_modes.md``.

Suppress a genuine exception with ``# nocheck: network-allowlist`` on (or
above) the offending line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

RULE = "network-allowlist"
SINK = re.compile(
    r"(aliasgroup\d+\s*=|\"(?:redirectUris|webOrigins|post\.logout\.redirect\.uris)\"\s*:|trusted_domains)(?P<value>.*)$"
)
MECHANISM = re.compile(r"network_urls|network_siblings|redirect_uris")
HOST_LOOKUP = re.compile(
    r"lookup\(\s*['\"](?:tls|domain|domains|canonical_url|landing_url)['\"]"
)
NAME = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b")
SET = re.compile(r"{%-?\s*set\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)-?%}")
MAX_DEPTH = 4


def _definitions(text: str, role_vars: dict) -> dict[str, str]:
    names = {key: str(value) for key, value in role_vars.items()}
    names.update(dict(SET.findall(text)))
    return names


def _verdict(value: str, names: dict[str, str], depth: int = 0) -> str:
    """Return ``aligned``, ``hostless`` or ``unaligned`` for one expression.

    Args:
        value: the Jinja expression or YAML value to classify.
        names: variable name -> definition, from ``{% set %}`` and role vars.
        depth: recursion depth through variable references.
    """
    if MECHANISM.search(value):
        return "aligned"
    verdicts = {"unaligned"} if HOST_LOOKUP.search(value) else set()
    if depth < MAX_DEPTH:
        for name in set(NAME.findall(value)) & names.keys():
            verdicts.add(_verdict(names[name], names, depth + 1))
    if "aligned" in verdicts:
        return "aligned"
    return "unaligned" if "unaligned" in verdicts else "hostless"


def violations(text: str, role_vars: dict, rel: str) -> list[str]:
    names = _definitions(text, role_vars)
    lines = text.splitlines()
    found = []
    for index, line in enumerate(lines):
        match = SINK.search(line)
        if not match or _verdict(match.group("value"), names) != "unaligned":
            continue
        if is_suppressed_at(lines, index, RULE):
            continue
        found.append(f"{rel}:{index + 1}: {line.strip()}")
    return found


def _role_vars(role_dir) -> dict:
    path = role_dir / ROLE_FILE_VARS_MAIN
    if not path.is_file():
        return {}
    return load_yaml_str(read_text(str(path))) or {}


class TestNetworkAllowlistSinks(unittest.TestCase):
    def test_once_rendered_allowlists_name_every_network_sibling(self):
        found = []
        for path in iter_project_files(extensions=(".j2",)):
            rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
            parts = rel.split("/")
            if len(parts) < 4 or parts[0] != "roles" or parts[2] != "templates":
                continue
            role_vars = _role_vars(PROJECT_ROOT / "roles" / parts[1])
            found.extend(violations(read_text(str(path)), role_vars, rel))
        self.assertEqual(
            found,
            [],
            "Allowlists rendered once per role must list every network "
            "sibling (lookup('network_urls', ...) or "
            "lookup('network_siblings', ...)):\n" + "\n".join(found),
        )

    def test_a_single_canonical_host_is_reported(self):
        role_vars = {
            "WOPI": "{{ lookup('tls', lookup('domain', 'web-app-nextcloud'), 'url.origin') }}"
        }
        self.assertEqual(
            violations("aliasgroup1={{ WOPI }}\n", role_vars, "env.j2"),
            ["env.j2:1: aliasgroup1={{ WOPI }}"],
        )

    def test_a_sibling_union_passes(self):
        role_vars = {
            "WOPI": "{% for d in lookup('network_siblings', lookup('domain', 'x')) %}{{ d }}{% endfor %}"
        }
        self.assertEqual(
            violations("aliasgroup1={{ WOPI }}\n", role_vars, "env.j2"), []
        )

    def test_a_set_binding_through_network_urls_passes(self):
        text = (
            "{% set web = lookup('network_urls', lookup('tls', 'x', 'url.origin')) %}\n"
            '"webOrigins": {{ web | to_json }},\n'
        )
        self.assertEqual(violations(text, {}, "c.json.j2"), [])

    def test_a_hostless_value_passes(self):
        self.assertEqual(
            violations('"post.logout.redirect.uris": "+",\n', {}, "r.json.j2"), []
        )

    def test_the_marker_suppresses(self):
        text = (
            "# nocheck: network-allowlist  single-network peer\n"
            "aliasgroup1={{ lookup('domain', 'x') }}\n"
        )
        self.assertEqual(violations(text, {}, "env.j2"), [])


if __name__ == "__main__":
    unittest.main()
