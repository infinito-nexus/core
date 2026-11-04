"""Lint: a role's ``meta/`` or ``vars/`` payload never carries Jinja in a mapping key.

Ansible renders the values of a loaded variable structure and leaves its keys
alone, so an expression written as a key reaches the consumer as its own source
text. ``web-app-nextcloud``'s sociallogin provider stored

    "groupMapping": {"/{{ lookup('rbac_group_path', ...) }}": "admin"}

in Nextcloud, which matches no group Keycloak ever sends, and the administrator
logging in through OIDC stayed out of the ``admin`` group. ``web-app-zammad``
and ``web-app-erpnext`` then repeated the shape in ``vars/main.yml``, which the
earlier ``meta/``-only scan did not reach, and every Zammad account that signed
in through the identity provider kept the Customer role it was created with.

Write the whole mapping as one expression instead, which ``jinja2_native``
returns as a real mapping with the key computed::

    groupMapping: >-
      {{ { '/' ~ lookup('rbac_group_path', ...): 'admin' } }}

Keys come from the YAML node graph, not from a line scan, so the body of a
block scalar (a rendered stylesheet, a shell script, a Jinja ``{% for %}`` that
emits ``name: value`` pairs into a generated file) is a value and is never
mistaken for a key.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: jinja-mapping-key`` on, or directly above, the offending line.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "jinja-mapping-key"
_SCANNED_DIRS = ("meta", "vars")


def _key_nodes(node: yaml.Node, seen: set[int] | None = None):
    """Yield every scalar node that stands as a mapping key below *node*.

    Args:
        node: the composed YAML node to walk.
        seen: ids of the nodes already walked. An alias makes the same node
            reachable twice and a self-referencing anchor makes the graph
            cyclic, which would otherwise recurse until RecursionError, a
            crash yaml.YAMLError does not cover.
    """
    seen = set() if seen is None else seen
    if id(node) in seen:
        return
    seen.add(id(node))
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            if isinstance(key_node, yaml.ScalarNode):
                yield key_node
            yield from _key_nodes(key_node, seen)
            yield from _key_nodes(value_node, seen)
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            yield from _key_nodes(item, seen)


def jinja_mapping_keys() -> list[str]:
    findings = []
    for path, content in iter_project_files_with_content(extensions=(".yml",)):
        parts = Path(path).relative_to(PROJECT_ROOT).parts
        if len(parts) < 3 or parts[0] != "roles" or parts[2] not in _SCANNED_DIRS:
            continue
        rel = Path(path).relative_to(PROJECT_ROOT)
        try:
            documents = list(yaml.compose_all(content))
        except yaml.YAMLError as error:
            findings.append(
                f"{rel}:0: unreadable YAML, the key check could not run ({error.__class__.__name__})"
            )
            continue
        lines = content.splitlines()
        for document in documents:
            if document is None:
                continue
            for key_node in _key_nodes(document):
                if "{{" not in key_node.value:
                    continue
                number = key_node.start_mark.line + 1
                if is_suppressed_at(lines, number, _RULE):
                    continue
                findings.append(f"{rel}:{number}: {lines[number - 1].strip()[:80]}")
    return sorted(set(findings))


class TestNoJinjaInMappingKeys(unittest.TestCase):
    def test_no_role_payload_expects_a_key_to_be_rendered(self) -> None:
        findings = jinja_mapping_keys()
        self.assertEqual(
            [],
            findings,
            f"Jinja expression(s) used as a mapping key ({len(findings)}). "
            "Ansible renders the values of a loaded variable structure and "
            "leaves the keys as written, so the consumer receives the source "
            "text. Write the whole mapping as one expression instead:\n"
            + "\n".join(f"  - {f}" for f in findings),
        )


if __name__ == "__main__":
    unittest.main()
