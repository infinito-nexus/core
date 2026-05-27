"""Validate `~`-concatenated path expressions in `lookup('config', ...)`.

The literal-path scanner only sees the first quoted string and falls
back to wildcard-prefix matching for paths ending in `.`, which is too
permissive. This test reconstructs the full path with `*` placeholders
for every Jinja variable segment and validates the wildcard path
against the same fallback chain the literal-path test uses.

The classifier owns the rule "concat-pattern match → wildcard path
keyed by `(role_id, wildcard_path)`". `role_id` resolves from the
literal app argument when present, otherwise from the file's
``roles/<role>/...`` location.
"""

import unittest
from collections.abc import Iterable, Mapping

from ._scan import (
    LookupMatch,
    expr_to_wildcard_path,
    get_context,
    iter_matches,
    role_id_from_path,
)
from ._validate import match_wildcard_path, match_wildcard_segment


def _build_wildcard_paths(
    matches: Iterable[LookupMatch],
) -> dict[tuple[str, str], list[tuple]]:
    out: dict[tuple[str, str], list[tuple]] = {}
    for m in matches:
        if m.kind != "concat":
            continue
        wildcard_path = expr_to_wildcard_path(m.path_arg)
        if wildcard_path is None:
            continue
        if m.app_literal is not None:
            role_id = m.app_literal
        else:
            role_id = role_id_from_path(m.file)
        if role_id is None:
            continue
        out.setdefault((role_id, wildcard_path), []).append((m.file, m.lineno))
    return out


class TestWildcardPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = get_context()
        cls.wildcard_paths = _build_wildcard_paths(iter_matches())

    def test_wildcard_paths(self):
        if not self.wildcard_paths:
            self.skipTest("No `~`-concatenated lookup paths found")
        failures: list[str] = []
        for (role_id, wildcard_path), occs in self.wildcard_paths.items():
            cfg = self.ctx.application_defaults.get(role_id)
            if cfg is None:
                continue
            if self._resolves(cfg, role_id, wildcard_path):
                continue
            file_path, lineno = occs[0]
            failures.append(
                f"wildcard path '{wildcard_path}' has no match in application "
                f"defaults / schema for role '{role_id}'; called at "
                f"{file_path}:{lineno}"
            )
        if failures:
            self.fail(
                f"{len(failures)} wildcard lookup path mismatch(es):\n"
                + "\n".join(f"- {f}" for f in failures)
            )

    def _resolves(self, cfg, role_id: str, wildcard_path: str) -> bool:
        ctx = self.ctx
        if match_wildcard_path(cfg, wildcard_path):
            return True
        if wildcard_path.startswith("users."):
            sub = wildcard_path.split(".", 1)[1]
            if match_wildcard_path({"_root": ctx.user_defaults}, "_root." + sub):
                return True
        if wildcard_path.startswith("credentials."):
            sub = wildcard_path.split(".", 1)[1]
            creds_cfg = cfg.get("credentials")
            if isinstance(creds_cfg, Mapping) and match_wildcard_segment(
                creds_cfg, sub
            ):
                return True
            schema = ctx.role_schemas.get(role_id, {})
            creds = schema.get("credentials") if isinstance(schema, Mapping) else None
            if isinstance(creds, Mapping) and match_wildcard_segment(creds, sub):
                return True
        return bool(
            wildcard_path.startswith("images.")
            and isinstance(cfg.get("images"), Mapping)
        )


if __name__ == "__main__":
    unittest.main()
