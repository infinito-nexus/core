"""Validate every literal `lookup('config', '<app_id>', '<path>')` call
resolves against the role's application defaults / schema.

The classifier here owns the rule "literal app id + complete path
(does NOT end with `.`)" — partial paths and variable-app calls are
handled by the sibling tests."""

import unittest
from collections.abc import Iterable

from utils.roles.applications.config import ConfigEntryNotSetError, get

from ._scan import LookupMatch, get_context, iter_matches
from ._validate import PathNotFoundError, validate_app_path


def _build_literal_paths(
    matches: Iterable[LookupMatch],
) -> dict[str, dict[str, list[tuple]]]:
    out: dict[str, dict[str, list[tuple]]] = {}
    for m in matches:
        if m.kind != "literal":
            continue
        if m.app_literal is None:
            continue
        if m.path_arg.endswith("."):
            continue
        out.setdefault(m.app_literal, {}).setdefault(m.path_arg, []).append(
            (m.file, m.lineno)
        )
    return out


class TestLiteralPaths(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = get_context()
        cls.literal_paths = _build_literal_paths(iter_matches())

    def test_literal_paths(self):
        ctx = self.ctx
        failures: list[str] = []
        missing_apps: list[str] = []
        for app_id, paths in self.literal_paths.items():
            if app_id not in ctx.application_defaults:
                missing_apps.append(app_id)
                continue
            for dotted, occs in paths.items():
                try:
                    get(
                        applications=ctx.application_defaults,
                        application_id=app_id,
                        config_path=dotted,
                        strict=True,
                    )
                except ConfigEntryNotSetError:
                    continue
                except Exception:
                    pass  # best-effort: tolerate other get() errors, validation is checked below
                try:
                    validate_app_path(
                        ctx.application_defaults,
                        ctx.role_schemas,
                        ctx.user_defaults,
                        app_id,
                        dotted,
                    )
                except PathNotFoundError as exc:
                    file_path, lineno = occs[0]
                    failures.append(f"{exc}; called at {file_path}:{lineno}")

        report: list[str] = []
        if missing_apps:
            report.append(
                f"{len(missing_apps)} application id(s) referenced by literal "
                f"lookups but missing in application defaults:"
            )
            report.extend(f"- {a}" for a in sorted(set(missing_apps)))
        if failures:
            report.append(f"{len(failures)} literal lookup path mismatch(es):")
            report.extend(f"- {f}" for f in failures)
        if report:
            self.fail("\n".join(report))


if __name__ == "__main__":
    unittest.main()
