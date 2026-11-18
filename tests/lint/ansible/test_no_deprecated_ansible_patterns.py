"""Lint: forbid Ansible constructs that are deprecated or break with fact injection off.

Each pattern below has a non-deprecated replacement. Keeping them out of the
tree means the compose deploy's deprecation gate
(assert_no_deprecation_warnings.sh) stays green and ``inject_facts_as_vars =
False`` in ``ansible.cfg`` stays safe.

Forbidden (with fix):

* ``ansible.builtin.apt_repository`` / ``apt_repository:`` -- deprecated module.
  Write the ``.list`` via ``ansible.builtin.copy`` (the repo's apt_repo.sh keeps
  the canonical .list and deletes .sources, so deb822_repository is unusable
  here) plus an explicit ``apt: update_cache``.
* ``community.mysql.*`` / ``ansible.mysql.*`` -- every database this project
  runs is MariaDB, which ``ansible.mysql`` warns about and drops in 6.0.0. Use
  ``ansible.mariadb.mariadb_<module>`` and keep ``ansible.mariadb`` in both
  requirements files.
* top-level injected facts (``ansible_os_family``, ``ansible_eth0`` and every
  other ``ansible_<name>``) -- ``ansible.cfg`` turns fact injection off, so a
  top-level fact is undefined. Use ``ansible_facts['<name>']``. Every
  ``ansible_<name>`` that is not a magic or connection variable
  (``ALLOWED_NAMES``, ``ALLOWED_PREFIXES``) counts as a fact. The ``(?!=)``
  guard skips a literal log label such as ``ansible_virtualization_type={{ ...
  }}`` (name glued to ``=``) while still flagging a comparison like
  ``ansible_os_family == 'X'`` (space before ``==``). In Python the rule reads
  only subscript and ``.get`` keys, the shape of a variable read.

Scans ``.yml`` / ``.yaml`` / ``.j2`` under roles/, tasks/, group_vars/,
playbooks/ and the playbook, and ``.py`` outside tests/ and role ``files/``. Mark a genuine
exception with ``# nocheck: deprecated-ansible`` same-or-above the line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "deprecated-ansible"
SCAN_SUFFIXES = (".yml", ".yaml", ".j2", ".py")
_YAML_PREFIXES = ("roles/", "tasks/", "group_vars/", "playbooks/", "playbook.yml")
_PY_EXCLUDED_PREFIXES = ("tests/",)
_PY_EXCLUDED_PARTS = ("/files/",)

ALLOWED_NAMES = frozenset(
    {
        "ansible_facts",
        "ansible_local",
        "ansible_check_mode",
        "ansible_config_file",
        "ansible_collection_name",
        "ansible_dependent_role_names",
        "ansible_diff_mode",
        "ansible_forks",
        "ansible_index_var",
        "ansible_inventory_sources",
        "ansible_limit",
        "ansible_loop",
        "ansible_loop_var",
        "ansible_parent_role_names",
        "ansible_parent_role_paths",
        "ansible_play_batch",
        "ansible_play_hosts",
        "ansible_play_hosts_all",
        "ansible_play_name",
        "ansible_play_role_names",
        "ansible_playbook_python",
        "ansible_role_name",
        "ansible_role_names",
        "ansible_run_tags",
        "ansible_search_path",
        "ansible_skip_tags",
        "ansible_verbosity",
        "ansible_version",
        "ansible_failed_task",
        "ansible_failed_result",
        "ansible_job_id",
        "ansible_host",
        "ansible_port",
        "ansible_user",
        "ansible_password",
        "ansible_connection",
        "ansible_private_key_file",
        "ansible_pipelining",
        "ansible_timeout",
        "ansible_remote_tmp",
        "ansible_docker_extra_args",
    }
)
ALLOWED_PREFIXES = (
    "ansible_become",
    "ansible_ssh_",
    "ansible_shell_",
    "ansible_winrm_",
    "ansible_paramiko_",
)
ALLOWED_SUFFIXES = ("_interpreter",)

_YAML_NAME = re.compile(r"\bansible_[A-Za-z0-9_]+\b(?!=)")
_PY_NAME = re.compile(r"(?:\[\s*|\.get\(\s*)[\"'](ansible_[A-Za-z0-9_]+)[\"']")

_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "apt_repository",
        re.compile(r"(?:ansible\.builtin\.)?apt_repository\s*:"),
        "deprecated module -> write the .list via ansible.builtin.copy + apt update_cache",
    ),
    (
        "mysql-collection",
        re.compile(r"\b(?:community|ansible)\.mysql\."),
        "MariaDB leaves the mysql collection in 6.0.0 -> use ansible.mariadb.mariadb_<module> (ansible.mariadb in both requirements files)",
    ),
)
_FACT_FIX = "top-level injected fact, undefined with fact injection off -> use ansible_facts['<name>']"


def is_fact_name(name: str) -> bool:
    """Tell whether *name* is a fact rather than a magic or connection variable.

    Args:
        name: an ``ansible_<name>`` identifier.

    Returns:
        ``True`` when the name is neither allowed explicitly nor by prefix or suffix.
    """
    return not (
        name in ALLOWED_NAMES
        or name.startswith(ALLOWED_PREFIXES)
        or name.endswith(ALLOWED_SUFFIXES)
    )


def scan_text(text: str, python: bool) -> list[str]:
    """Return one issue line per forbidden construct in *text*.

    Args:
        text: the file content.
        python: read *text* as Python (subscript and ``.get`` keys only) instead
            of YAML or Jinja.
    """
    lines = text.splitlines()
    out: list[str] = []
    fact_pattern = _PY_NAME if python else _YAML_NAME
    patterns = () if python else _PATTERNS
    for idx, line in enumerate(lines, start=1):
        if is_suppressed_at(lines, idx, _RULE, mode="same-or-above"):
            continue
        for kind, pattern, fix in patterns:
            if pattern.search(line):
                out.append(f"line {idx}: [{kind}] {line.strip()}  -> {fix}")
        for match in fact_pattern.finditer(line):
            name = match.group(1) if python else match.group(0)
            if is_fact_name(name):
                out.append(
                    f"line {idx}: [injected-fact] {line.strip()}  -> {_FACT_FIX}"
                )
    return out


def _in_scope(rel: str) -> bool:
    if rel.endswith(".py"):
        return not rel.startswith(_PY_EXCLUDED_PREFIXES) and not any(
            part in f"/{rel}" for part in _PY_EXCLUDED_PARTS
        )
    return rel.startswith(_YAML_PREFIXES)


class TestNoDeprecatedAnsiblePatterns(unittest.TestCase):
    def test_no_deprecated_patterns(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for abs_path in iter_project_files(extensions=SCAN_SUFFIXES):
            rel = Path(abs_path).relative_to(PROJECT_ROOT).as_posix()
            if not _in_scope(rel):
                continue
            try:
                text = read_text(str(abs_path))
            except (OSError, UnicodeDecodeError):
                continue
            issues = scan_text(text, python=rel.endswith(".py"))
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

    def test_a_planted_top_level_fact_read_is_caught(self) -> None:
        planted = {
            "when: ansible_os_family == 'Debian'": False,
            "{{ ansible_eth0.ipv4.address }}": False,
            "{{ hostvars[h]['ansible_default_ipv4'] }}": False,
            'distro = task_vars.get("ansible_distribution")': True,
            'facts = task_vars["ansible_mounts"]': True,
        }
        for line, python in planted.items():
            with self.subTest(line=line):
                self.assertTrue(scan_text(line, python=python), line)

    def test_magic_connection_and_namespaced_reads_pass(self) -> None:
        clean = {
            "when: ansible_facts['os_family'] == 'Debian'": False,
            "{{ ansible_host }} {{ ansible_become_password }}": False,
            "{{ ansible_python_interpreter }} {{ ansible_loop_var }}": False,
            "msg: ansible_virtualization_type={{ x }}": False,
            'facts = task_vars.get("ansible_facts") or {}': True,
            'host = hostvars[h].get("ansible_host")': True,
            "ansible_playbook = shutil.which('ansible-playbook')": True,
        }
        for line, python in clean.items():
            with self.subTest(line=line):
                self.assertEqual(scan_text(line, python=python), [], line)


if __name__ == "__main__":
    unittest.main()
