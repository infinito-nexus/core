from __future__ import annotations

import glob
from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils import PROJECT_ROOT

DEFAULTS: dict[str, Any] = {
    "owner": "root",
    "group": "root",
    "mode": "0640",
    "condition": True,
    "notify": ["compose-up"],
}


def _glob_files(pattern: str) -> list[str]:
    """Paths matching *pattern*, files only, sorted.

    Args:
        pattern: an absolute glob pattern.

    Returns:
        Sorted absolute paths; directories are dropped, mirroring Ansible's
        ``fileglob``.
    """
    return sorted(path for path in glob.glob(pattern) if Path(path).is_file())


def _strip_j2(name: str) -> str:
    """*name* without a trailing ``.j2``."""
    return name.removesuffix(".j2")


def _expand_glob_entry(entry: dict, application_id: str) -> list[dict]:
    """One ``src_glob`` entry turned into one dict per matched template.

    Args:
        entry: the role_templates entry carrying ``src_glob`` and ``dest_dir``.
        application_id: role whose ``templates/`` directory is globbed.

    Returns:
        One rendered-template spec per match, sorted by source path.

    Raises:
        AnsibleError: ``dest_dir`` is missing or not a string.
    """
    dest_dir = entry.get("dest_dir")
    if not isinstance(dest_dir, str) or not dest_dir:
        raise AnsibleError(
            "role_templates_expanded: an entry with 'src_glob' requires a "
            f"non-empty string 'dest_dir', got {dest_dir!r}"
        )

    templates_dir = PROJECT_ROOT / "roles" / application_id / "templates"
    out: list[dict] = []
    for path in _glob_files(str(templates_dir / str(entry["src_glob"]))):
        item = {key: entry.get(key, value) for key, value in DEFAULTS.items()}
        item["src"] = path
        item["dest"] = dest_dir.rstrip("/") + "/" + _strip_j2(Path(path).name)
        out.append(item)
    return out


class LookupModule(LookupBase):
    def run(self, terms, variables: dict | None = None, **kwargs):
        """Expand ``role_templates`` into one spec per template to render.

        Args:
            terms: ``[application_id, role_templates]``.

        Returns:
            A single-element list holding the expanded spec list, so the caller
            receives the list itself rather than its first element.

        Raises:
            AnsibleError: wrong term count, empty application_id, or an entry
                that is not a dict.
        """
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "role_templates_expanded: exactly two terms required "
                "(application_id, role_templates)"
            )

        application_id = str(terms[0] or "").strip()
        if not application_id:
            raise AnsibleError("role_templates_expanded: application_id is empty")

        entries = terms[1]
        if entries is None:
            return [[]]
        if not isinstance(entries, list):
            raise AnsibleError(
                f"role_templates_expanded: role_templates must be a list, got {type(entries)}"
            )

        out: list[dict] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise AnsibleError(
                    f"role_templates_expanded: every entry must be a dict, got {type(entry)}"
                )
            if "src_glob" in entry:
                out.extend(_expand_glob_entry(entry, application_id))
                continue
            item = dict(entry)
            for key, value in DEFAULTS.items():
                item.setdefault(key, value)
            out.append(item)
        return [out]
