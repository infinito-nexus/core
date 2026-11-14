from __future__ import annotations

import shlex
import unittest
from pathlib import Path

import yaml

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_COMMAND_MODULES = frozenset(
    {"ansible.builtin.command", "command", "ansible.builtin.shell", "shell"}
)
_DNF = frozenset({"dnf", "dnf5", "yum", "microdnf"})
_ASSUME_YES = frozenset({"-y", "--assumeyes"})
_READ_ONLY = frozenset(
    {
        "check-update",
        "clean",
        "info",
        "list",
        "provides",
        "repolist",
        "repoquery",
        "search",
    }
)


def _words(value: yaml.Node) -> list[str]:
    if isinstance(value, yaml.ScalarNode):
        try:
            return shlex.split(value.value)
        except ValueError:
            return []
    if not isinstance(value, yaml.MappingNode):
        return []
    items = {k.value: v for k, v in value.value if isinstance(k, yaml.ScalarNode)}
    argv = items.get("argv")
    if isinstance(argv, yaml.SequenceNode):
        return [n.value for n in argv.value if isinstance(n, yaml.ScalarNode)]
    cmd = items.get("cmd")
    return _words(cmd) if isinstance(cmd, yaml.ScalarNode) else []


def prompts(words: list[str]) -> bool:
    """
    Args:
        words: the argv of one command.

    Returns:
        Whether the words run a dnf subcommand that may ask a question
        without ``-y`` to answer it.
    """
    if words[:1] == ["sudo"]:
        words = words[1:]
    if not words or Path(words[0]).name not in _DNF:
        return False
    flags = set(words[1:])
    subcommand = next((w for w in words[1:] if not w.startswith("-")), "")
    return subcommand not in _READ_ONLY and not flags & _ASSUME_YES


def offending_lines(node: yaml.Node) -> list[int]:
    """
    Args:
        node: a composed YAML node of an Ansible file.

    Returns:
        The lines of every command task that runs a prompting dnf call.
    """
    if isinstance(node, yaml.SequenceNode):
        return [line for child in node.value for line in offending_lines(child)]
    if not isinstance(node, yaml.MappingNode):
        return []
    found = []
    for key, value in node.value:
        if not isinstance(key, yaml.ScalarNode):
            continue
        if key.value in _COMMAND_MODULES and prompts(_words(value)):
            found.append(key.start_mark.line + 1)
        found += offending_lines(value)
    return found


def offenders(rel: str, content: str) -> list[str]:
    """
    Args:
        rel: the file's path relative to the repository root.
        content: the file's text.

    Returns:
        ``<rel>:<line>`` for every prompting dnf call in ``content``.
    """
    try:
        docs = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
    except yaml.YAMLError:
        return []
    return [f"{rel}:{line}" for doc in docs for line in offending_lines(doc)]


def _ansible_files():
    for path, content in iter_project_files_with_content(
        extensions=(".yml", ".yaml"), exclude_tests=True
    ):
        rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
        if any(name in content for name in _DNF) and rel.startswith(
            ("roles/", "tasks/", "playbooks/")
        ):
            yield rel, content


class TestDnfCommandsAssumeYes(unittest.TestCase):
    def test_every_prompting_dnf_command_passes_assume_yes(self) -> None:
        found = sorted(
            entry
            for rel, content in _ansible_files()
            for entry in offenders(rel, content)
        )
        if found:
            self.fail(
                "A dnf call without `-y` that can ask a question (a repository "
                "key import, a transaction) reads no answer under Ansible and "
                "declines it; `dnf makecache --refresh` failed so with "
                "`repomd.xml GPG signature verification error: Signing key not "
                "found`. Add `-y`:\n" + "\n".join(f"  - {entry}" for entry in found)
            )

    def test_makecache_without_assume_yes_is_found(self) -> None:
        text = "- ansible.builtin.command:\n    argv: [dnf, makecache, --refresh]\n"
        self.assertEqual(offenders("x.yml", text), ["x.yml:1"])

    def test_makecache_with_assume_yes_passes(self) -> None:
        text = "- ansible.builtin.command:\n    argv: [dnf, makecache, --refresh, -y]\n"
        self.assertEqual(offenders("x.yml", text), [])

    def test_a_read_only_subcommand_passes(self) -> None:
        text = "- ansible.builtin.command:\n    argv: [dnf, clean, metadata]\n"
        self.assertEqual(offenders("x.yml", text), [])

    def test_a_shell_string_is_split(self) -> None:
        text = "- ansible.builtin.shell: sudo /usr/bin/dnf install foo\n"
        self.assertEqual(offenders("x.yml", text), ["x.yml:1"])

    def test_a_cmd_key_inside_a_block_is_found(self) -> None:
        text = (
            "- block:\n    - command:\n        cmd: yum --assumeyes upgrade\n"
            "    - command:\n        cmd: microdnf upgrade\n"
        )
        self.assertEqual(offenders("x.yml", text), ["x.yml:4"])

    def test_another_program_is_ignored(self) -> None:
        text = "- command:\n    argv: [apt-get, update]\n"
        self.assertEqual(offenders("x.yml", text), [])


if __name__ == "__main__":
    unittest.main()
