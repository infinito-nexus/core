"""Catch role-local ``ansible.builtin.template:`` task modules that
write into a path bind-mounted in the role's ``compose.yml.j2``.

A role-local template render still works in compose mode, but in swarm
mode the file only lands on the manager node and the bind mount on
workers points at a non-existent path. The fix is to replace the inline
``template:`` task with an include of
``roles/sys-svc-compose/tasks/utils/render_replicated_templates.yml``,
which renders locally AND replicates the file to every swarm peer.

The check parses task files as YAML (not regex) so that lists passed
via ``vars: role_templates: [...]`` to the central helper are NOT
mistaken for inline ``template:`` tasks. Opt-out per call site via
``# nocheck: volumes-template-spot`` on the ``dest:`` line for
legitimate exceptions (e.g. files that aren't bind-mounted into a
container).
"""

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_TEMPL_COMPOSE

from . import PROJECT_ROOT

NOCHECK_RE = re.compile(r"#\s*nocheck:\s*volumes-template-spot")
HELPER_PATH = "roles/sys-svc-compose/tasks/utils/render_replicated_templates.yml"
TEMPLATE_MODULE_KEYS = {"template", "ansible.builtin.template"}


def _role_for_path(path: str) -> str | None:
    p = Path(path)
    try:
        rel = p.relative_to(PROJECT_ROOT / "roles")
    except ValueError:
        return None
    return rel.parts[0] if rel.parts else None


def _bind_mount_host_vars(compose_text: str) -> set[str]:
    """Every host-side ``{{ VAR }}`` from compose ``- "{{ HOST }}:{{ CONTAINER }}"`` mount lines."""
    names: set[str] = set()
    line_re = re.compile(
        r"""^\s*-\s*["']?\{\{\s*([A-Z][A-Z0-9_]*)\s*\}\}\s*:\{\{""",
        re.MULTILINE,
    )
    for m in line_re.finditer(compose_text):
        names.add(m.group(1))
    return names


def _iter_template_tasks(data):
    """Yield each inline ``template:`` task's spec from a parsed task list.

    Recurses into ``block:`` / ``rescue:`` / ``always:`` so tasks nested
    under a block are still discovered.
    """
    if not isinstance(data, list):
        return
    for entry in data:
        if not isinstance(entry, dict):
            continue
        for key in TEMPLATE_MODULE_KEYS:
            spec = entry.get(key)
            if isinstance(spec, dict):
                yield spec
        for nested_key in ("block", "rescue", "always"):
            nested = entry.get(nested_key)
            if isinstance(nested, list):
                yield from _iter_template_tasks(nested)


class TestVolumesTemplateRenderCentralized(unittest.TestCase):
    def test_no_role_local_template_to_bind_mounted_host_path(self):
        offenders: list[str] = []
        for file_path in iter_project_files(extensions=(".yml",)):
            role = _role_for_path(file_path)
            if role is None:
                continue
            if "/tasks/" not in file_path:
                continue
            if file_path.endswith(HELPER_PATH):
                continue
            compose = PROJECT_ROOT / "roles" / role / ROLE_FILE_TEMPL_COMPOSE
            if not compose.is_file():
                continue
            compose_text = read_text(str(compose))
            host_vars = _bind_mount_host_vars(compose_text)
            if not host_vars:
                continue
            try:
                data = load_yaml_any(file_path)
            except Exception:
                continue
            if not isinstance(data, list):
                continue
            content = read_text(file_path)
            content_lines = content.splitlines()
            for spec in _iter_template_tasks(data):
                dest = spec.get("dest")
                if not isinstance(dest, str):
                    continue
                referenced = next((var for var in host_vars if var in dest), None)
                if referenced is None:
                    continue
                line = _dest_line_no(content_lines, referenced)
                if line and NOCHECK_RE.search(content_lines[line - 1]):
                    continue
                offenders.append(
                    f"{file_path}:{line}: role-local template render into "
                    f"bind-mounted '{{{{ {referenced} }}}}' bypasses the "
                    f"swarm + NFS chain. Replace the inline 'template:' "
                    f"task with an include of the central helper "
                    f"'{HELPER_PATH}' "
                    f"(pass the list under vars: role_templates: [...]); "
                    f"or add '# nocheck: volumes-template-spot' to the "
                    f"line for legitimate exceptions."
                )
        if offenders:
            self.fail(
                "Role-local template renders that should flow through the "
                "central render_replicated_templates.yml helper so the file "
                "is replicated to every swarm peer:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


def _dest_line_no(content_lines: list[str], host_var: str) -> int:
    """Find the ``dest:`` line that references the given host_var."""
    for idx, raw in enumerate(content_lines, start=1):
        stripped = raw.lstrip()
        if not stripped.startswith("dest:"):
            continue
        if host_var in raw:
            return idx
    return 0


if __name__ == "__main__":
    unittest.main()
