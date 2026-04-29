"""Guard: the pre-005 `[RBAC.GROUP.NAME, ...] | path_join` idiom MUST NOT
appear in production code after requirement 005 is implemented.

Every OIDC group path MUST be derived from the `rbac_group_path` lookup
plugin. Inline `path_join` constructions scatter the path shape across
many files and make future layout changes partial; requirement 005's
callsite-migration clause explicitly forbids them.

Exceptions allowed by this guard:
- `group_vars/` may define RBAC.GROUP.NAME itself.
- `plugins/lookup/` contains the replacement (rbac_group_path).
- `docs/` is allowed for archival/historic references.
- `roles/web-app-keycloak/vars/main.yml` exposes KEYCLOAK_RBAC_GROUP_NAME
  as a simple variable alias, not as a path construction; allow it.
"""

import os
import re
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))

PATH_JOIN_PATTERN = re.compile(
    r"\[\s*RBAC\.GROUP\.NAME\s*,\s*.+?\]\s*\|\s*path_join",
    re.DOTALL,
)

ALLOWED_RELATIVE_PREFIXES = (
    "group_vars/",
    "plugins/lookup/",
    "docs/",
    # KEYCLOAK_RBAC_GROUP_NAME is a pure alias, not a path construction.
    "roles/web-app-keycloak/vars/main.yml",
    # This guard's own file mentions the forbidden pattern literally.
    "tests/integration/oauth2_oidc/test_rbac_path_join_guard.py",
)

EXCLUDED_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    ".venvs",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".cache",
    "dist",
    "build",
}


def _is_allowed(rel_path):
    return any(rel_path.startswith(p) for p in ALLOWED_RELATIVE_PREFIXES)


def _iter_text_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for filename in filenames:
            if not (
                filename.endswith(".yml")
                or filename.endswith(".yaml")
                or filename.endswith(".j2")
                or filename.endswith(".py")
            ):
                continue
            yield os.path.join(dirpath, filename)


class TestRbacPathJoinIsForbidden(unittest.TestCase):
    def test_no_inline_rbac_group_name_path_join_in_production_code(self):
        offenders = []
        for path in _iter_text_files(REPO_ROOT):
            rel = os.path.relpath(path, REPO_ROOT)
            if _is_allowed(rel):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            if PATH_JOIN_PATTERN.search(content):
                offenders.append(rel)
        self.assertEqual(
            offenders,
            [],
            msg=(
                "Requirement 005 forbids `[RBAC.GROUP.NAME, ...] | path_join` "
                "outside of group_vars/, plugins/lookup/, docs/, and the "
                "Keycloak variable alias. Migrate the following files to "
                "lookup('rbac_group_path', ...):\n" + "\n".join(offenders)
            ),
        )


if __name__ == "__main__":
    unittest.main()
