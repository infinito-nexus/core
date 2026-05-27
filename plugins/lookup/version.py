"""
Ansible lookup plugin: version

No parameters.
Reads ``pyproject.toml`` from the repository root, located by walking
parents from this plugin file's location.

Resolution order:
1) [project].version (PEP 621)
2) [tool.poetry].version (Poetry fallback)
"""

from __future__ import annotations

from pathlib import Path

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.lookup import PROJECT_ROOT

try:
    import tomllib  # Python 3.11+
except Exception:
    try:
        import tomli as tomllib
    except Exception as exc:
        raise AnsibleError(
            "version lookup requires 'tomllib' (Python 3.11+) "
            "or the 'tomli' package installed on the control node."
        ) from exc


def _get_nested(data: dict, path: list[str]):
    cur = data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        # Intentionally ignore terms/kwargs — no parameters supported

        pyproject_path = str(PROJECT_ROOT / "pyproject.toml")

        if not Path(pyproject_path).exists():
            raise AnsibleError(f"version lookup: file not found: {pyproject_path}")

        try:
            with Path(pyproject_path).open("rb") as f:
                data = tomllib.load(f)
        except Exception as exc:
            raise AnsibleError(
                f"version lookup: failed to parse TOML: {pyproject_path}: {exc}"
            ) from exc

        version = _get_nested(data, ["project", "version"])
        if not version:
            version = _get_nested(data, ["tool", "poetry", "version"])

        if not version or not isinstance(version, str) or not version.strip():
            raise AnsibleError(
                f"version lookup: could not extract version from {pyproject_path}. "
                "Tried [project].version and [tool.poetry].version."
            )

        return [version.strip()]
