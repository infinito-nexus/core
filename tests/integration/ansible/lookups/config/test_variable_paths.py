"""Validate `lookup('config', <var>, '<path>')` calls whose path is a
literal but whose application argument is templated. The path must
exist somewhere in the project (any application, any schema). For a
stricter per-role check see :mod:`test_role_local_paths`.

The classifier here captures every literal-pattern match that is NOT
a fully-literal lookup (which lands in :mod:`test_literal_paths`):
* literal app + partial path (ends with `.`)
* variable app + any path
"""

import unittest
from collections.abc import Iterable, Mapping

from ._scan import LookupMatch, get_context, iter_matches
from ._validate import PathNotFoundError, assert_nested


def _build_variable_paths(
    matches: Iterable[LookupMatch],
) -> dict[str, list[tuple]]:
    out: dict[str, list[tuple]] = {}
    for m in matches:
        if m.kind != "literal":
            continue
        # A literal app + complete path goes to literal_paths, not here.
        if m.app_literal is not None and not m.path_arg.endswith("."):
            continue
        out.setdefault(m.path_arg, []).append((m.file, m.lineno))
    return out


class TestVariablePaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = get_context()
        cls.variable_paths = _build_variable_paths(iter_matches())

    def test_variable_paths(self):
        if not self.variable_paths:
            self.skipTest("No dynamic lookup('config', ...) calls")
        failures: list[str] = []
        for dotted, occs in self.variable_paths.items():
            if self._resolves_anywhere(dotted):
                continue
            file_path, lineno = occs[0]
            failures.append(f"No entry for '{dotted}'; called at {file_path}:{lineno}")
        if failures:
            self.fail(
                f"{len(failures)} variable lookup path(s) without any match:\n"
                + "\n".join(f"- {f}" for f in failures)
            )

    def _resolves_anywhere(self, dotted: str) -> bool:
        ctx = self.ctx
        for schema in ctx.role_schemas.values():
            if isinstance(schema, Mapping) and dotted in schema:
                return True

        if dotted.endswith("."):
            prefix_keys = dotted.rstrip(".").split(".")
            for cfg in ctx.application_defaults.values():
                cur = cfg
                ok = True
                for p in prefix_keys:
                    if isinstance(cur, Mapping) and p in cur:
                        cur = cur[p]
                    else:
                        ok = False
                        break
                if ok:
                    return True

        if dotted.startswith("credentials."):
            key = dotted.split(".", 1)[1]
            for cfg in ctx.application_defaults.values():
                creds = cfg.get("credentials", {}) if isinstance(cfg, Mapping) else {}
                if isinstance(creds, Mapping) and key in creds:
                    return True
            for schema in ctx.role_schemas.values():
                creds = (
                    schema.get("credentials", {}) if isinstance(schema, Mapping) else {}
                )
                if isinstance(creds, Mapping) and key in creds:
                    return True

        if dotted.startswith("images.") and any(
            isinstance(cfg.get("images"), Mapping)
            for cfg in ctx.application_defaults.values()
        ):
            return True

        if dotted.startswith("users."):
            subpath = dotted.split(".", 1)[1]
            try:
                assert_nested(ctx.user_defaults, subpath, "user_defaults")
            except PathNotFoundError:
                pass
            else:
                return True

        for cfg in ctx.application_defaults.values():
            try:
                assert_nested(cfg, dotted, "application_defaults")
            except PathNotFoundError:
                pass
            else:
                return True
        return False


if __name__ == "__main__":
    unittest.main()
