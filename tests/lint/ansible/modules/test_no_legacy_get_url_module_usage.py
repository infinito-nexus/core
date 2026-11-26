"""Downloads go through ``get_url_retry`` so a transient outage costs a retry,
not the deploy.

The one exception is an ``ansible.builtin.get_url`` task that always runs
async: ``get_url_retry`` retries in a loop on the controller, which
async_wrapper cannot run, so its caller collects the job and retries it. Only
an ``async`` that can never turn the task synchronous counts: a positive
integer, or ``{{ <name> }}`` for a name in ``_ALWAYS_ASYNC_NAMES``, each of
which its role clamps to at least 1. Any other templated value can resolve to
``omit`` (``ASYNC_TIME`` does when async is off) or to 0, so the task would
run synchronously without a retry, whatever ``retries``/``until`` it carries:
its synchronous branch belongs in a ``get_url_retry`` task, whose timeout
spans every retry.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

LEGACY_GET_URL_MODULE_PATTERN = re.compile(
    r"^\s*(ansible\.builtin\.get_url|get_url)\s*:\s*(?:#.*)?$"
)
_QUALIFIED = "ansible.builtin.get_url"
_ALWAYS_ASYNC_NAMES = frozenset({"lmstudio_fetch_lifetime"})
_ALWAYS_ASYNC_RE = re.compile(
    r"^(?:[1-9]\d*|\{\{\s*(?:[1-9]\d*|(?P<name>[A-Za-z_]\w*))\s*\}\})$"
)


def _always_async(node: yaml.Node | None) -> list[int]:
    """Find the get_url calls below ``node`` whose task always runs async.

    Args:
        node: a composed YAML node of an Ansible file.

    Returns:
        The 0-based line of the ``ansible.builtin.get_url`` key of every task
        whose own ``async`` can never turn it synchronous.
    """
    if isinstance(node, yaml.SequenceNode):
        return [line for child in node.value for line in _always_async(child)]
    if not isinstance(node, yaml.MappingNode):
        return []
    keys = {
        key.value: (key, value)
        for key, value in node.value
        if isinstance(key, yaml.ScalarNode)
    }
    found = []
    if _QUALIFIED in keys and "async" in keys:
        gate = keys["async"][1]
        match = (
            _ALWAYS_ASYNC_RE.match(gate.value.strip())
            if isinstance(gate, yaml.ScalarNode)
            else None
        )
        if match and match.group("name") in (None, *_ALWAYS_ASYNC_NAMES):
            found.append(keys[_QUALIFIED][0].start_mark.line)
    for _, value in node.value:
        found += _always_async(value)
    return found


def exempt_lines(content: str) -> set[int]:
    """Tell which get_url lines of a file are allowed async downloads.

    Args:
        content: the file's text.

    Returns:
        The 0-based line of every allowed ``ansible.builtin.get_url`` key; empty
        when the file is no valid YAML.
    """
    try:
        documents = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return set()
    return {line for document in documents for line in _always_async(document)}


class TestNoLegacyGetUrlModuleUsage(unittest.TestCase):
    def test_no_legacy_get_url_module_call_is_used(self):
        """
        Enforce migration from legacy get_url module calls to get_url_retry.
        """
        findings: list[tuple[str, int, str]] = []

        for path_str, content in iter_project_files_with_content(extensions=(".yml",)):
            yml_file = Path(path_str)
            rel = yml_file.relative_to(PROJECT_ROOT).as_posix()
            lines = content.splitlines()
            exempt: set[int] | None = None
            for line_no, line in enumerate(lines, start=1):
                if not LEGACY_GET_URL_MODULE_PATTERN.match(line):
                    continue
                if exempt is None:
                    exempt = exempt_lines(content)
                if line_no - 1 in exempt:
                    continue
                findings.append((rel, line_no, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(
                    findings, key=lambda item: (item[0], item[1])
                )
            )
            self.fail(
                "Found legacy get_url module calls in .yml files.\n\n"
                "Please migrate all of them to `get_url_retry:` so deploys are resilient against "
                "transient network outages. Only a task that always runs async may call "
                "`ansible.builtin.get_url`, since get_url_retry cannot run async; put its "
                "synchronous branch in a separate get_url_retry task.\n\n"
                f"{formatted}"
            )


class TestAsyncGetUrlExemption(unittest.TestCase):
    def _task(self, *keys: str) -> str:
        """
        Args:
            keys: task lines after the module block.

        Returns:
            A two-task file whose first task calls ansible.builtin.get_url on line 1.
        """
        return "\n".join(
            [
                "- name: Download",
                "  ansible.builtin.get_url:",
                "    url: https://example.org/model.gguf",
                "    dest: /tmp/model.gguf",
                *keys,
                "- name: Next",
                "  ansible.builtin.debug:",
            ]
        )

    def test_a_task_without_async_is_flagged(self):
        self.assertNotIn(1, exempt_lines(self._task()))

    def test_an_unqualified_async_call_is_flagged(self):
        text = self._task('  async: "{{ 60 }}"').replace(
            "ansible.builtin.get_url:", "get_url:"
        )
        self.assertNotIn(1, exempt_lines(text))

    def test_an_async_task_that_can_run_sync_without_retries_is_flagged(self):
        text = self._task('  async: "{{ 60 if ASYNC_ENABLED | bool else omit }}"')
        self.assertNotIn(1, exempt_lines(text))

    def test_retries_do_not_exempt_a_task_that_can_run_sync(self):
        text = self._task(
            '  async: "{{ 60 if ASYNC_ENABLED | bool else omit }}"',
            "  retries: 0",
            "  until: true",
        )
        self.assertNotIn(1, exempt_lines(text))

    def test_a_ternary_omit_gate_is_flagged(self):
        text = self._task('  async: "{{ ASYNC_ENABLED | bool | ternary(60, omit) }}"')
        self.assertNotIn(1, exempt_lines(text))

    def test_a_templated_async_that_can_resolve_to_omit_is_flagged(self):
        self.assertNotIn(1, exempt_lines(self._task('  async: "{{ ASYNC_TIME }}"')))

    def test_a_zero_async_is_flagged(self):
        self.assertNotIn(1, exempt_lines(self._task("  async: 0")))

    def test_an_async_outside_the_task_keys_is_flagged(self):
        self.assertNotIn(1, exempt_lines(self._task("  vars:", "    async: 60")))

    def test_an_always_async_task_is_exempt(self):
        self.assertIn(1, exempt_lines(self._task('  async: "{{ 60 }}"')))

    def test_the_fetch_round_async_form_is_exempt(self):
        text = self._task('  async: "{{ lmstudio_fetch_lifetime }}"')
        self.assertIn(1, exempt_lines(text))

    def test_a_nested_list_item_does_not_split_the_task(self):
        text = self._task(
            "  loop:",
            "    - first",
            "    - second",
            '  async: "{{ lmstudio_fetch_lifetime }}"',
        )
        self.assertIn(1, exempt_lines(text))

    def test_a_nested_list_item_does_not_lend_its_async_to_the_task(self):
        self.assertNotIn(1, exempt_lines(self._task("  loop:", "    - async: 60")))


if __name__ == "__main__":
    unittest.main()
