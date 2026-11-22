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
  ``ansible_<name>`` that is not a magic variable (``MAGIC_NAMES``) or a
  variable a connection, become or shell plugin declares for its options (read
  from the plugins' ``DOCUMENTATION``) counts as a fact. The facts that
  ``service_facts``, ``package_facts`` and ``getent`` set without the prefix
  (``services``, ``packages``, ``getent_<db>``) are flagged when read bare
  inside a Jinja expression or a condition line. The ``(?!=(?!=))``
  guard skips a literal log label such as ``ansible_virtualization_type={{ ...
  }}`` (name glued to a single ``=``) while still flagging a comparison like
  ``ansible_os_family == 'X'`` or ``ansible_os_family=='X'``. In Python the rule reads
  only subscript and ``.get`` keys, the shape of a variable read.

Scans ``.yml`` / ``.yaml`` / ``.j2`` under roles/, tasks/, group_vars/,
playbooks/, compose/, inventories/ and both playbooks, and ``.py`` outside
tests/ and role ``files/``. Mark a genuine
exception with ``# nocheck: deprecated-ansible`` same-or-above the line.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from ansible import constants

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

_RULE = "deprecated-ansible"
SCAN_SUFFIXES = (".yml", ".yaml", ".j2", ".py")
_YAML_PREFIXES = (
    "roles/",
    "tasks/",
    "group_vars/",
    "playbooks/",
    "compose/",
    "inventories/",
    "playbook.yml",
    "playbook-sync.yml",
)
_PY_EXCLUDED_PREFIXES = ("tests/",)
_PY_EXCLUDED_PARTS = ("/files/",)
_ANSIBLE_PLUGINS = Path(constants.__file__).parent / "plugins"
_PLUGIN_DOC_DIRS = (
    _ANSIBLE_PLUGINS / "connection",
    _ANSIBLE_PLUGINS / "become",
    _ANSIBLE_PLUGINS / "shell",
    _ANSIBLE_PLUGINS / "doc_fragments",
    PROJECT_ROOT / "plugins" / "connection",
)


def declared_plugin_vars(directories: tuple[Path, ...]) -> frozenset[str]:
    """Return every ``ansible_*`` variable a plugin option declares under ``vars:``.

    Args:
        directories: plugin directories whose ``.py`` files carry a
            ``DOCUMENTATION`` string, at module or class level.

    Returns:
        The declared variable names.
    """
    names: set[str] = set()
    for directory in directories:
        for path in sorted(directory.glob("*.py")):
            for node in ast.walk(ast.parse(read_text(str(path)))):
                if not (
                    isinstance(node, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == "DOCUMENTATION"
                        for target in node.targets
                    )
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    continue
                options = (load_yaml_str(node.value.value) or {}).get("options") or {}
                for option in options.values():
                    for var in (option or {}).get("vars") or []:
                        name = var.get("name", "") if isinstance(var, dict) else ""
                        if name.startswith("ansible_"):
                            names.add(name)
    return frozenset(names)


MAGIC_NAMES = frozenset(
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
    }
)
ALLOWED_NAMES = (
    MAGIC_NAMES
    | declared_plugin_vars(_PLUGIN_DOC_DIRS)
    | frozenset(
        name for names in constants.MAGIC_VARIABLE_MAPPING.values() for name in names
    )
)
ALLOWED_SUFFIXES = ("_interpreter",)

_YAML_NAME = re.compile(r"\bansible_[A-Za-z0-9_]+\b(?!=(?!=))")
_PY_NAME = re.compile(r"(?:\[\s*|\.get\(\s*)[\"'](ansible_[A-Za-z0-9_]+)[\"']")
_BARE_FACT = re.compile(
    r"(?<![\w.'\"/-])(?:services|packages|getent_[a-z]+)\b"
    r"(?=\s*(?:\[|\.\w|\||\s+is\s|==|!=|\s+in\b|\s*\)|\s*}}|\s*%}))"
)
_JINJA_EXPR = re.compile(r"\{\{.*?\}\}|\{%.*?%\}")
_CONDITION_KEY = re.compile(
    r"^\s*(?:-\s+)?(?P<key>when|that|failed_when|changed_when|until):(?:\s+(?P<expr>.*))?$"
)
_CONDITION_ITEM = re.compile(r"^\s*-(?!\s+[\w\"']+:)\s+(?P<expr>.*)$")

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
_BARE_FACT_FIX = (
    "fact without the ansible_ prefix (service_facts, package_facts, getent), "
    "undefined with fact injection off -> use ansible_facts['<name>']"
)


def is_fact_name(name: str) -> bool:
    """Tell whether *name* is a fact rather than a magic or connection variable.

    Args:
        name: an ``ansible_<name>`` identifier.

    Returns:
        ``True`` when the name is neither allowed explicitly nor by suffix.
    """
    return not (name in ALLOWED_NAMES or name.endswith(ALLOWED_SUFFIXES))


def scan_text(text: str, python: bool, template: bool = False) -> list[str]:
    """Return one issue line per forbidden construct in *text*.

    Args:
        text: the file content.
        python: read *text* as Python (subscript and ``.get`` keys only) instead
            of YAML or Jinja.
        template: read *text* as a Jinja template, whose list items are output,
            not conditions.
    """
    lines = text.splitlines()
    out: list[str] = []
    fact_pattern = _PY_NAME if python else _YAML_NAME
    patterns = () if python else _PATTERNS
    condition_column: int | None = None
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
        if python or line.lstrip().startswith("#"):
            continue
        expressions = _JINJA_EXPR.findall(line)
        if not template and line.strip():
            column = len(line) - len(line.lstrip())
            if condition_column is not None and column > condition_column:
                expressions.append(line.strip())
            else:
                condition_column = None
                key = _CONDITION_KEY.match(line)
                item = None if key else _CONDITION_ITEM.match(line)
                if key:
                    condition_column = key.start("key")
                    expressions.append(key.group("expr") or "")
                elif item:
                    expressions.append(item.group("expr"))
        if any(_BARE_FACT.search(expression) for expression in expressions):
            out.append(
                f"line {idx}: [injected-bare-fact] {line.strip()}  -> {_BARE_FACT_FIX}"
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
            issues = scan_text(
                text, python=rel.endswith(".py"), template=rel.endswith(".j2")
            )
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
            "when: ansible_os_family=='Debian'": False,
            "{{ ansible_eth0.ipv4.address }}": False,
            "{{ hostvars[h]['ansible_default_ipv4'] }}": False,
            'distro = task_vars.get("ansible_distribution")': True,
            'facts = task_vars["ansible_mounts"]': True,
            "when: services['docker.service'] is defined": False,
            "- packages['nfs-ganesha'] | first": False,
            "- getent_group is defined": False,
            "{{ getent_passwd.nixbld1[1] }}": False,
            "- when: services['docker.service'] is defined": False,
            "when: >\n  x is defined and\n  services['docker.service'] is defined": False,
            "failed_when: |-\n  rc != 0 or packages['git'] | length == 0": False,
            "when: x is defined and\n  getent_group is defined": False,
        }
        for line, python in planted.items():
            with self.subTest(line=line):
                self.assertTrue(scan_text(line, python=python), line)

    def test_every_option_var_of_the_lab_connection_is_allowed(self) -> None:
        for name in ("ansible_docker_extra_env", "ansible_docker_working_dir"):
            with self.subTest(name=name):
                self.assertEqual(scan_text(f"{name}: x", python=False), [], name)

    def test_magic_connection_and_namespaced_reads_pass(self) -> None:
        clean = {
            "when: ansible_facts['os_family'] == 'Debian'": False,
            "{{ ansible_host }} {{ ansible_become_password }}": False,
            "{{ ansible_python_interpreter }} {{ ansible_loop_var }}": False,
            "msg: ansible_virtualization_type={{ x }}": False,
            'facts = task_vars.get("ansible_facts") or {}': True,
            'host = hostvars[h].get("ansible_host")': True,
            "ansible_playbook = shutil.which('ansible-playbook')": True,
            "when: ansible_facts.services['docker.service'] is defined": False,
            "{{ lookup('config', application_id, 'services.sso.enabled') }}": False,
            "- name: install language packages": False,
            "when: >\n  x is defined\nvars:\n  services: [a]": False,
            "- when: x is defined\n  name: list packages | services": False,
        }
        for line, python in clean.items():
            with self.subTest(line=line):
                self.assertEqual(scan_text(line, python=python), [], line)


if __name__ == "__main__":
    unittest.main()
