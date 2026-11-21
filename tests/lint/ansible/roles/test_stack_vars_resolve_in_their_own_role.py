from __future__ import annotations

import re
import unittest

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES

_RULE = "stack-var-foreign-scope"
STACK_KEY = "stack"
CHECKOUT_KEY = "checkout"

_SCOPED_RE = re.compile(r"(?<![\w.])(application_id|entity_name)\b")


def reads_the_scope(line: str) -> bool:
    """Return whether *line* reads a role-scoped variable.

    Args:
        line: a single source line.
    """
    return any(
        not line[: match.start()].rstrip().endswith("|")
        for match in _SCOPED_RE.finditer(line)
    )


def _child(node, key: str):
    if not isinstance(node, yaml.MappingNode):
        return None
    return next(
        (
            value
            for name, value in node.value
            if isinstance(name, yaml.ScalarNode) and name.value == key
        ),
        None,
    )


def _scalars(node) -> list[tuple[int, str]]:
    if isinstance(node, yaml.ScalarNode):
        return [(node.start_mark.line + 1, node.value)]
    if isinstance(node, yaml.MappingNode):
        return [found for _name, value in node.value for found in _scalars(value)]
    if isinstance(node, yaml.SequenceNode):
        return [found for item in node.value for found in _scalars(item)]
    return []


def checkout_values(text: str) -> list[tuple[int, str]]:
    """
    Args:
        text: the content of a ``meta/services.yml``.

    Returns:
        ``(line, value)`` of every scalar under ``stack.checkout``, nested
        ones included.
    """
    checkout = _child(_child(yaml.compose(text), STACK_KEY), CHECKOUT_KEY)
    if not isinstance(checkout, yaml.MappingNode):
        return []
    return _scalars(checkout)


def _services_files() -> list:
    return sorted((PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}"))


def checkout_values_reading_foreign_scope() -> list[str]:
    findings = []
    for path in _services_files():
        text = read_text(str(path))
        lines = text.splitlines()
        for line, value in checkout_values(text):
            if not reads_the_scope(value) or is_suppressed_at(lines, line, _RULE):
                continue
            findings.append(
                f"{path.relative_to(PROJECT_ROOT)}:{line}: a {STACK_KEY}.{CHECKOUT_KEY} "
                "value resolves against whichever role reads it"
            )
    return findings


class TestStackVarsResolveInTheirOwnRole(unittest.TestCase):
    def test_no_checkout_value_reads_the_reader_s_scope(self) -> None:
        findings = checkout_values_reading_foreign_scope()
        self.assertEqual(
            [],
            findings,
            f"value(s) that resolve against the wrong role ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_shape_it_guards_is_actually_in_use(self) -> None:
        handing = [
            path for path in _services_files() if checkout_values(read_text(str(path)))
        ]
        self.assertGreater(len(handing), 3, "no role hands its sources to the stack")

    def test_a_value_reading_the_scope_is_found(self) -> None:
        text = (
            "stack:\n"
            "  checkout:\n"
            "    ref: \"{{ lookup('config', 'web-app-x', 'services.'"
            " ~ ('web-app-x' | entity_name) ~ '.ref') }}\"\n"
            "    url: \"{{ lookup('config', application_id, 'services.x.repository') }}\"\n"
            "other:\n"
            "  checkout:\n"
            '    url: "{{ application_id }}"\n'
        )
        self.assertEqual(
            [line for line, value in checkout_values(text) if reads_the_scope(value)],
            [4],
        )

    def test_a_nested_build_value_reading_the_scope_is_found(self) -> None:
        text = (
            "stack:\n"
            "  checkout:\n"
            "    build:\n"
            "      bases:\n"
            "        node: \"node@{{ lookup('config', application_id, 'services.node.version') }}\"\n"
            "      dockerfiles:\n"
            "        app: Dockerfile\n"
        )
        self.assertEqual(
            [line for line, value in checkout_values(text) if reads_the_scope(value)],
            [5],
        )


if __name__ == "__main__":
    unittest.main()
