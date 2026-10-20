"""
Ansible lookup plugin: version

Reads ``pyproject.toml`` from the repository root, located by walking
parents from this plugin file's location.

Args:
    terms: empty for the project's own version, resolved as
        1) [project].version (PEP 621)
        2) [tool.poetry].version (Poetry fallback);
        or one distribution name, for the version its exact ``==`` pin in
        [project.dependencies] names.
"""

from __future__ import annotations

from pathlib import Path

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.lookup import PROJECT_ROOT

try:
    import tomllib
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


def _dependency_pin(data: dict, package: str, pyproject_path: str) -> str:
    prefix = f"{package}=="
    for requirement in _get_nested(data, ["project", "dependencies"]) or []:
        if isinstance(requirement, str) and requirement.startswith(prefix):
            return requirement[len(prefix) :].strip()
    raise AnsibleError(
        f"version lookup: {package} has no exact '==' pin in "
        f"[project.dependencies] of {pyproject_path}."
    )


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):

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

        if len(terms) > 1:
            raise AnsibleError(
                "version lookup accepts at most one term: a distribution name"
            )
        if terms:
            return [_dependency_pin(data, str(terms[0]), pyproject_path)]

        version = _get_nested(data, ["project", "version"])
        if not version:
            version = _get_nested(data, ["tool", "poetry", "version"])

        if not version or not isinstance(version, str) or not version.strip():
            raise AnsibleError(
                f"version lookup: could not extract version from {pyproject_path}. "
                "Tried [project].version and [tool.poetry].version."
            )

        return [version.strip()]
