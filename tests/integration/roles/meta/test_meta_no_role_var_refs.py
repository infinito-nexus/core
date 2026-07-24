"""Meta-files are static schema, NOT runtime templates.

``roles/*/meta/*.yml`` are loaded by static tooling (registry builders,
config caches, schema validators) that do not run Ansible's templar
with the role's runtime variables in scope. Embedding role-vars from
``vars/main.yml`` inside meta values produces a stringly-typed value at
the static layer (literal ``{{ MY_VAR }}``) and at best silently
non-functional behavior at the Ansible layer, depending on the call
site.

This test fails when any ``{{ IDENTIFIER }}`` inside a meta file's
value references a key declared in the same role's
``vars/main.yml``. Ansible magic / cross-role lookups (``group_names``,
``inventory_hostname``, ``application_id``, ``entity_name``, ``lookup(...)``
calls, etc.) are allowed because they resolve outside the role's local
vars file.
"""

import re
import unittest

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

JINJA_IDENT_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)")

ANSIBLE_BUILTINS = {
    "ansible_architecture",
    "ansible_become_password",
    "ansible_distribution",
    "ansible_distribution_release",
    "ansible_env",
    "ansible_facts",
    "ansible_memtotal_mb",
    "ansible_os_family",
    "ansible_processor_vcpus",
    "ansible_service_mgr",
    "ansible_virtualization_role",
    "ansible_virtualization_type",
    "application_id",
    "entity_name",
    "group_names",
    "groups",
    "hostvars",
    "inventory_hostname",
    "inventory_dir",
    "item",
    "lookup",
    "omit",
    "playbook_dir",
    "role_name",
    "role_path",
    "true",
    "false",
    "none",
}


def _role_var_keys(role_dir) -> set[str]:
    vars_yml = role_dir / ROLE_FILE_VARS_MAIN
    if not vars_yml.is_file():
        return set()
    data = load_yaml_any(str(vars_yml)) or {}
    if not isinstance(data, dict):
        return set()
    return {k for k in data if isinstance(k, str)}


def _iter_strings(value, path: tuple = ()):
    if isinstance(value, str):
        yield path, value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield from _iter_strings(v, (*path, str(k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _iter_strings(v, (*path, f"[{i}]"))


class TestMetaNoRoleVarRefs(unittest.TestCase):
    def test_meta_files_do_not_reference_role_vars(self):
        offenders: list[str] = []
        for role_dir in sorted(
            p for p in (PROJECT_ROOT / "roles").iterdir() if p.is_dir()
        ):
            meta_dir = role_dir / "meta"
            if not meta_dir.is_dir():
                continue
            role_vars = _role_var_keys(role_dir)
            if not role_vars:
                continue
            for meta_file in sorted(meta_dir.glob("*.yml")):
                text = read_text(str(meta_file))
                try:
                    data = load_yaml_any(str(meta_file))
                except Exception:
                    continue
                if data is None:
                    continue
                for path, value in _iter_strings(data):
                    for match in JINJA_IDENT_RE.finditer(value):
                        ident = match.group(1)
                        if ident in ANSIBLE_BUILTINS:
                            continue
                        if ident not in role_vars:
                            continue
                        line = _approx_line(text, value)
                        offenders.append(
                            f"{meta_file.relative_to(PROJECT_ROOT)}:{line}: "
                            f"value at '{'.'.join(path)}' references "
                            f"role-var '{ident}' from vars/main.yml — meta "
                            f"files are static schema and the templar is "
                            f"not guaranteed to be in scope when they are "
                            f"loaded. Use a literal value, derive it via "
                            f"lookup() from another meta key, or move the "
                            f"declaration to vars/main.yml."
                        )
        if offenders:
            self.fail(
                "Meta files MUST NOT reference role-vars from vars/main.yml:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


def _approx_line(text: str, needle: str) -> int:
    idx = text.find(needle)
    if idx < 0:
        return 0
    return text[:idx].count("\n") + 1


if __name__ == "__main__":
    unittest.main()
