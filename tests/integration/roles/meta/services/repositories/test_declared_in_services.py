"""Integration guard: every git-clone URL referenced inside a role
(Dockerfile, tasks, templates, files) MUST be declared as a
`repository:` value in that role's ``meta/services.yml``.

The same applies symmetrically to git refs: any `compose_repository_ref`
or `--branch <ref>` (clone) value that ties to a declared
`repository:` MUST come from the same role's ``meta/services.yml``
under `ref:`. Hardcoded git URLs / refs in task files or Dockerfiles
silently bypass the entity contract enforced by
``test_requires_ref.py`` and the unified naming convention.

Scope
=====
Per-role recursive scan of ``roles/<role>/`` for any literal HTTPS
git URL (matches ``https?://…/<…>.git``). Each match must appear
as a ``repository:`` value in ``roles/<role>/meta/services.yml``.

Detection
=========
* `https://example.com/foo/bar.git` literal in source → fail unless
  declared in the role's services.yml.
* The same role MAY reference the URL in multiple files; each
  reference is fine as long as the URL itself is declared once in
  services.yml.

Opt-out
=======
A specific call site that legitimately uses a literal git URL (for
example a plugin / build-helper / extension repo) can add
``# nocheck: repository-declared`` on the same line as the URL OR
on the line immediately preceding it (so Dockerfiles with `\\`
line continuation can put the marker on a standalone comment line).
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"

# Matches HTTPS git URLs of the form `https://host/<…>/<repo>.git`.
# Requires at least one `/<path>/` segment after the host AND that
# `.git` ends the URL path (followed by URL-terminator or end of
# string). Without the path requirement, hostnames like
# `raw.githubusercontent.com` partial-match as `https://raw.git`.
_GIT_URL_RE = re.compile(
    r"https?://[A-Za-z0-9.-]+(?:/[A-Za-z0-9._~-]+)+\.git(?=[\s\"'`<>?#/]|$)"
)

_OPTOUT_MARKER = "nocheck: repository-declared"

# File extensions worth scanning. Plus extensionless `Dockerfile`.
_SCAN_EXTENSIONS = (
    ".yml",
    ".yaml",
    ".j2",
    ".sh",
    ".py",
    ".rb",
    ".js",
    ".ts",
)


def _walk_repositories(node) -> set[str]:
    """Recursively collect every `repository:` string anywhere in the
    services.yml tree (top-level entity, sub-entity, plugin map, etc.)."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "repository" and isinstance(value, str) and value:
                found.add(value.strip())
            else:
                found |= _walk_repositories(value)
    elif isinstance(node, list):
        for item in node:
            found |= _walk_repositories(item)
    return found


def _collect_declared_repositories(services_path) -> set[str]:
    data = load_yaml_any(str(services_path), default_if_missing=None)
    return _walk_repositories(data)


def _iter_role_files(role_dir):
    """Every text file under the role that could plausibly contain a
    literal git URL. Uses the project-wide path cache so the scan
    re-uses what other tests already enumerated."""
    role_prefix = str(role_dir) + "/"
    yield from (
        p
        for p in iter_project_files(extensions=_SCAN_EXTENSIONS)
        if p.startswith(role_prefix)
    )
    # `files/Dockerfile` (no extension) is not picked up by the
    # extension filter; iterate the cache once more explicitly.
    for p in iter_project_files():
        if p.startswith(role_prefix) and p.endswith("/Dockerfile"):
            yield p


class TestDeclaredInServices(unittest.TestCase):
    def test_git_urls_in_role_files_are_declared_in_services_yml(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            role_name = role_dir.name
            services_path = role_dir / ROLE_FILE_META_SERVICES
            declared = (
                _collect_declared_repositories(services_path)
                if services_path.is_file()
                else set()
            )

            seen_paths: set[str] = set()
            for fpath in _iter_role_files(role_dir):
                if fpath in seen_paths:
                    continue
                seen_paths.add(fpath)
                # Skip the services.yml itself — the declaration is the
                # authoritative source we are checking against.
                if fpath.endswith("/" + ROLE_FILE_META_SERVICES):
                    continue
                try:
                    text = read_text(fpath)
                except (OSError, UnicodeDecodeError):
                    continue
                if "https://" not in text and "http://" not in text:
                    continue
                lines = text.splitlines()
                for line_no, line in enumerate(lines, 1):
                    if _OPTOUT_MARKER in line:
                        continue
                    # Marker on the preceding line also counts (handy
                    # for Dockerfile `\\` continuations and similar).
                    if line_no >= 2 and _OPTOUT_MARKER in lines[line_no - 2]:
                        continue
                    for m in _GIT_URL_RE.finditer(line):
                        url = m.group(0)
                        if url in declared:
                            continue
                        rel = fpath.split(str(PROJECT_ROOT) + "/", 1)[-1]
                        offenders.append(
                            f"{role_name}: {rel}:{line_no} "
                            f"references `{url}` but it is not declared "
                            f"as `repository:` in "
                            f"{role_name}/{ROLE_FILE_META_SERVICES}"
                        )

        if offenders:
            self.fail(
                f"{len(offenders)} hardcoded git URL(s) bypass the "
                f"`meta/services.yml` repository declaration:\n"
                + "\n".join(f"- {o}" for o in offenders)
            )
