"""Strict per-role check for `lookup('config', application_id, 'literal.path')`.

When a role file (under `roles/<role>/...`) calls
`lookup('config', application_id, 'a.b.c')`, the path must resolve
against `application_defaults[<role>]` — not merely against *some*
role, which is all :mod:`test_variable_paths` guarantees.
`application_id` is always equal to the role name in this repo (set in
`roles/<role>/vars/main.yml`), so the file-path-derived role is the
correct lookup context.

The classifier is intentionally narrow: the app argument MUST be the
literal identifier ``application_id``. Other variables like
``_BBB_COTURN_ROLE`` or ``oauth2_proxy_application_id`` explicitly
point at a different role at runtime and are out of scope for this
check (the runtime target is unknown to a static scan). Such calls
land in :mod:`test_variable_paths` instead, which only requires that
the path resolve *somewhere*. The file must additionally live in a
role that declares ``application_id`` in ``vars/main.yml``.

Mirrors the resolution logic of `plugins/lookup/config.py`:
- `users.<canonical>.<sub>`: requires the role's `meta/users.yml` to
  declare `<canonical>` AND the global `user_defaults[<canonical>]` to
  expose `<sub>`.
- `credentials.<key>`: same fallbacks as the literal-paths check.
- everything else: must walk the role's `application_defaults` entry.
"""

import unittest
from collections.abc import Iterable, Mapping

from ._scan import LookupMatch, get_context, iter_matches, role_id_from_path
from ._validate import PathNotFoundError, assert_nested, validate_app_path


def _build_role_local_paths(
    matches: Iterable[LookupMatch],
    roles_with_application_id: frozenset[str],
) -> dict[tuple[str, str], list[tuple]]:
    out: dict[tuple[str, str], list[tuple]] = {}
    for m in matches:
        if m.kind != "literal":
            continue
        # Only the literal `application_id` variable maps to "this role
        # reads its own config". Anything else (e.g. `_BBB_COTURN_ROLE`,
        # `oauth2_proxy_application_id`) explicitly targets a different
        # role at runtime and is intentionally out of scope here.
        if m.app_arg != "application_id":
            continue
        if m.path_arg.endswith("."):
            continue
        role_id = role_id_from_path(m.file)
        if role_id is None or role_id not in roles_with_application_id:
            continue
        out.setdefault((role_id, m.path_arg), []).append((m.file, m.lineno))
    return out


class TestRoleLocalLiteralPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = get_context()
        cls.role_local_paths = _build_role_local_paths(
            iter_matches(), cls.ctx.roles_with_application_id
        )

    def test_role_local_literal_paths(self):
        if not self.role_local_paths:
            self.skipTest("No role-local lookup('config', <var>, 'literal') calls")
        ctx = self.ctx
        failures: list[str] = []
        for (role_id, dotted), occs in self.role_local_paths.items():
            if role_id not in ctx.application_defaults:
                continue
            cfg = ctx.application_defaults[role_id]
            if dotted.startswith("users."):
                err = self._check_users_path(role_id, cfg, dotted, occs)
                if err:
                    failures.append(err)
                continue
            try:
                validate_app_path(
                    ctx.application_defaults,
                    ctx.role_schemas,
                    ctx.user_defaults,
                    role_id,
                    dotted,
                )
            except PathNotFoundError as exc:
                file_path, lineno = occs[0]
                failures.append(f"{exc}; called at {file_path}:{lineno}")
        if failures:
            self.fail(
                f"{len(failures)} role-local lookup path mismatch(es):\n"
                + "\n".join(f"- {f}" for f in failures)
            )

    def _check_users_path(self, role_id, cfg, dotted, occs) -> str | None:
        sub_parts = dotted.split(".", 2)
        if len(sub_parts) < 2:
            return None
        canonical = sub_parts[1]
        file_path, lineno = occs[0]
        role_users = cfg.get("users") if isinstance(cfg, Mapping) else None
        if not isinstance(role_users, Mapping):
            return (
                f"role '{role_id}' references '{dotted}' but has no users "
                f"mapping (declare '{canonical}' in roles/{role_id}/meta/"
                f"users.yml); called at {file_path}:{lineno}"
            )
        if canonical not in role_users:
            return (
                f"role '{role_id}' references '{dotted}' but '{canonical}' is "
                f"not declared in roles/{role_id}/meta/users.yml; called at "
                f"{file_path}:{lineno}"
            )
        if len(sub_parts) == 3:
            try:
                assert_nested(
                    self.ctx.user_defaults,
                    f"{canonical}.{sub_parts[2]}",
                    "user_defaults",
                )
            except PathNotFoundError as exc:
                return f"role '{role_id}': {exc}; called at {file_path}:{lineno}"
        return None


if __name__ == "__main__":
    unittest.main()
