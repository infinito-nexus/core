"""Guard: every role passed to `lookup('rbac_group_path', ...)` MUST be
declared in the target application's `meta/rbac.yml` (or be the implicit
`administrator` auto-added by the role-list contract).

Why this test exists
--------------------
At runtime the `rbac_group_path` lookup raises:

    rbac_group_path: role 'editor' is not declared under
    applications[web-app-joomla].rbac.roles.
    Declared roles: ['administrator'].

…which only fires when the playbook actually templates the offending file
on a target host. That is far too late: a typo in a Jinja template (or a
role that adds `role='editor'` without first adding `editor:` to its
`meta/rbac.yml`) becomes a deploy-time hard failure instead of a CI signal.

Contract this guard pins
------------------------
For every callsite of the form

    lookup('rbac_group_path', application_id=<app_id>, role=<role>, ...)

found anywhere under `roles/` (templates, vars, meta) — where both
`application_id` and `role` resolve to a literal string — the named
`<role>` MUST appear in `roles/<app_id>/meta/rbac.yml` under the top-level
`roles:` mapping, OR equal the implicit `administrator`.

Resolution rules:
- `application_id='web-app-foo'`  -> literal, used directly.
- `application_id=application_id` -> resolved via the enclosing role's
  `vars/main.yml` `application_id:` key (the universal convention in this
  repo). Roles that set `application_id` elsewhere are tracked too.
- Non-literal `role=` (e.g. `role=item` inside a loop) is skipped with a
  visible diagnostic on failure — those cases need a separate runtime
  check.

This guard is the static counterpart to the runtime contract enforced by
`plugins/lookup/rbac_group_path.py`. It does not replace the runtime
check (the lookup also validates tenancy/scope which are runtime data),
but it eliminates the most common class of failure: declaration drift
between callers and `meta/rbac.yml`.
"""

import os
import re
import unittest
from pathlib import Path

import yaml

from utils.cache.files import iter_project_files
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_RBAC

from . import PROJECT_ROOT

ROLES_DIR = str(PROJECT_ROOT / "roles")

IMPLICIT_ADMIN_ROLE = "administrator"

# Match a single rbac_group_path lookup call. `[^)]*` deliberately stops at
# the first `)` so multi-call lines stay segmented. Jinja convention in
# this repo keeps each lookup call on a single line.
LOOKUP_CALL = re.compile(
    r"""lookup\(\s*['"]rbac_group_path['"]\s*,\s*(?P<kwargs>[^)]*)\)""",
    re.DOTALL,
)

# Within the captured kwargs, pick up application_id and role. application_id
# is either a quoted literal or the bareword identifier `application_id`
# (the only identifier form used in the codebase, per repo convention).
APPLICATION_ID_KW = re.compile(
    r"""application_id\s*=\s*(?:'(?P<sq>[^']+)'|"(?P<dq>[^"]+)"|(?P<ident>[A-Za-z_]\w*))"""
)
ROLE_KW = re.compile(r"""role\s*=\s*(?:'(?P<sq>[^']+)'|"(?P<dq>[^"]+)")""")
ROLE_NON_LITERAL = re.compile(r"role\s*=\s*[A-Za-z_]\w*")

# File extensions where Jinja lookup() calls legitimately appear.
SCAN_EXTENSIONS = (".j2", ".yml", ".yaml")

# Files that mention `rbac_group_path` for documentation/contract reasons
# rather than as live callsites. They are excluded by absolute path so
# every other callsite stays in scope.
EXCLUDED_RELATIVE_PATHS = frozenset(
    {
        # The lookup plugin's own docstring shows usage examples.
        "plugins/lookup/rbac_group_path.py",
        # This guard contains the literal call form in its docstring.
        "tests/integration/oauth2_oidc/rbac/test_group_path_role_declarations.py",  # nocheck: self-path-reference
    }
)


def _read_text(path):
    try:
        with Path(path).open(encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _line_of(text, offset):
    """1-based line number of `offset` in `text`."""
    return text.count("\n", 0, offset) + 1


def _role_application_id(role_dir):
    """Return the role's declared `application_id` from vars/*.yml, or None.

    The repo convention is `vars/main.yml` with `application_id: "web-app-X"`
    on a top-level key. Some roles split vars into multiple files, so we
    scan every file under vars/ and return the first hit.
    """
    vars_dir = str(Path(role_dir) / "vars")
    if not Path(vars_dir).is_dir():
        return None
    pattern = re.compile(
        r"""^application_id:\s*["']?([^"'\s#]+)["']?\s*$""", re.MULTILINE
    )
    for entry in sorted(os.listdir(vars_dir)):
        if not entry.endswith((".yml", ".yaml")):
            continue
        text = _read_text(str(Path(vars_dir) / entry))
        if not text:
            continue
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def _declared_roles(application_id):
    """Roles declared in `roles/<application_id>/meta/rbac.yml` plus the
    implicit `administrator`. Returns None if the role directory does not
    exist (caller treats that as a separate kind of failure)."""
    role_dir = str(Path(ROLES_DIR) / application_id)
    if not Path(role_dir).is_dir():
        return None
    declared = {IMPLICIT_ADMIN_ROLE}
    rbac_yml = str(Path(role_dir) / ROLE_FILE_META_RBAC)
    if Path(rbac_yml).is_file():
        try:
            data = load_yaml_any(rbac_yml) or {}
        except yaml.YAMLError:
            data = {}
        roles_block = (data.get("roles") if isinstance(data, dict) else None) or {}
        if isinstance(roles_block, dict):
            declared.update(roles_block.keys())
    return declared


def _enclosing_role_dir(file_path):
    """Walk up from `file_path` until we hit a `roles/<role>/` segment;
    return the absolute path to that role directory, or None."""
    rel = os.path.relpath(file_path, ROLES_DIR)
    head = rel.split(os.sep, 1)[0]
    # nocheck: project-root-import  string-prefix check, not a path build
    if not head or head.startswith(".."):
        return None
    candidate = str(Path(ROLES_DIR) / head)
    return candidate if Path(candidate).is_dir() else None


def _iter_callsites():
    """Yield (rel_path, line_no, application_id_repr, role_repr, raw_kwargs)
    for every rbac_group_path lookup call under roles/."""
    roles_prefix = str(ROLES_DIR) + os.sep
    for abs_path in iter_project_files(extensions=SCAN_EXTENSIONS):
        if not abs_path.startswith(roles_prefix):
            continue
        if any(
            seg in abs_path
            for seg in (
                os.sep + "__pycache__" + os.sep,
                os.sep + "node_modules" + os.sep,
            )
        ):
            continue
        rel_path = os.path.relpath(abs_path, PROJECT_ROOT)
        if rel_path in EXCLUDED_RELATIVE_PATHS:
            continue
        text = _read_text(abs_path)
        if not text or "rbac_group_path" not in text:
            continue
        for call in LOOKUP_CALL.finditer(text):
            kwargs_blob = call.group("kwargs")
            yield rel_path, abs_path, _line_of(text, call.start()), kwargs_blob


class TestRbacGroupPathRoleDeclarations(unittest.TestCase):
    def test_every_callsite_role_is_declared(self):
        offenders = []  # hard failures
        unresolved = []  # soft notes for diagnostics

        for rel_path, abs_path, line_no, kwargs_blob in _iter_callsites():
            app_match = APPLICATION_ID_KW.search(kwargs_blob)
            role_match = ROLE_KW.search(kwargs_blob)

            if not app_match:
                offenders.append(
                    f"{rel_path}:{line_no}: lookup('rbac_group_path', ...) "
                    f"without an `application_id=` kwarg"
                )
                continue
            if not role_match:
                if ROLE_NON_LITERAL.search(kwargs_blob):
                    unresolved.append(
                        f"{rel_path}:{line_no}: role= is a non-literal "
                        f"expression; static check skipped"
                    )
                    continue
                offenders.append(
                    f"{rel_path}:{line_no}: lookup('rbac_group_path', ...) "
                    f"without a `role=` kwarg"
                )
                continue

            literal_app = app_match.group("sq") or app_match.group("dq")
            ident_app = app_match.group("ident")
            if literal_app:
                application_id = literal_app
            elif ident_app == "application_id":
                role_dir = _enclosing_role_dir(abs_path)
                application_id = _role_application_id(role_dir) if role_dir else None
                if not application_id:
                    offenders.append(
                        f"{rel_path}:{line_no}: application_id=application_id "
                        f"used, but the enclosing role does not declare "
                        f"`application_id:` in vars/"
                    )
                    continue
            else:
                # Some other identifier — out of scope for static analysis.
                unresolved.append(
                    f"{rel_path}:{line_no}: application_id={ident_app} is a "
                    f"non-standard identifier; static check skipped"
                )
                continue

            role = role_match.group("sq") or role_match.group("dq")

            declared = _declared_roles(application_id)
            if declared is None:
                offenders.append(
                    f"{rel_path}:{line_no}: application_id='{application_id}' "
                    f"does not correspond to an existing role under roles/"
                )
                continue

            if role not in declared:
                offenders.append(
                    f"{rel_path}:{line_no}: role='{role}' is not declared "
                    f"under applications[{application_id}].rbac.roles. "
                    f"Declared roles: {sorted(declared)}. "
                    f"Add `{role}:` to roles/{application_id}/meta/rbac.yml "
                    f"or fix the callsite."
                )

        # Surface unresolved items in the failure message so a future
        # contributor sees what this static check could not verify.
        if offenders:
            msg_lines = [
                "rbac_group_path callsites reference roles that are not declared in the target application's meta/rbac.yml. This is the static counterpart of the runtime AnsibleError raised by plugins/lookup/rbac_group_path.py.",
                "",
                "Offenders:",
                *(f"  - {item}" for item in offenders),
            ]
            if unresolved:
                msg_lines += [
                    "",
                    "Note — the following callsites were skipped by the static check (non-literal kwargs); verify them manually:",
                    *(f"  - {item}" for item in unresolved),
                ]
            self.fail("\n".join(msg_lines))


if __name__ == "__main__":
    unittest.main()
