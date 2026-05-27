"""Enforce contract for ``sys-svc-compose`` repository-clone variables.

Every ``include_role: { name: sys-stk-* }`` that drives a git clone via
``compose_repository_url`` must:

1. Pass the URL as a Jinja expression (no inline literal URLs in task
   files — keeps repo coordinates in ``vars/main.yml`` or inventory).
2. Pair the URL with a ``compose_repository_ref`` in the same vars
   block — pinning a clone source without pinning the ref leaves
   deploys non-reproducible (clones drift with upstream HEAD).
3. Pass the ref as a Jinja expression too, for the same SPOT reason.

The lint walks every dict in every .yml/.yaml file rather than only
``include_role`` task shapes, so the rule holds wherever the variables
appear (defaults, vars files, host_vars, …).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import iter_project_files_with_content
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator

URL_KEY = "compose_repository_url"
REF_KEY = "compose_repository_ref"


def _is_jinja_expression(value: object) -> bool:
    """Accept any string that embeds a ``{{ … }}`` substitution —
    pure Jinja and mixed-literal forms (e.g. ``"stable/{{ FOO }}"``,
    ``"{{ BAR }}.git"``) both pass; plain string literals fail."""
    return isinstance(value, str) and "{{" in value and "}}" in value


def _walk_dicts(node: object) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_dicts(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk_dicts(item)


class TestComposeRepositoryUrlRef(unittest.TestCase):
    def test_compose_repository_url_and_ref_use_jinja_and_are_paired(self):
        url_literals: list[tuple[str, object]] = []
        ref_literals: list[tuple[str, object]] = []
        missing_ref: list[tuple[str, object]] = []

        for path_str, _ in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            yml_file = Path(path_str)
            try:
                data = load_yaml_any(str(yml_file), default_if_missing=None)
            except Exception:
                continue
            if data is None:
                continue

            rel = yml_file.relative_to(PROJECT_ROOT).as_posix()

            for node in _walk_dicts(data):
                url = node.get(URL_KEY)
                ref = node.get(REF_KEY)
                if url is not None:
                    if not _is_jinja_expression(url):
                        url_literals.append((rel, url))
                    if ref is None:
                        missing_ref.append((rel, url))
                if ref is not None and not _is_jinja_expression(ref):
                    ref_literals.append((rel, ref))

        errors: list[str] = []
        if url_literals:
            errors.append(
                f"{URL_KEY} MUST be a Jinja expression (e.g. "
                f'`"{{{{ MYAPP_REPO }}}}"`), not an inline literal:\n'
                + "\n".join(
                    f"  - {path}: {val!r}" for path, val in sorted(url_literals)
                )
            )
        if ref_literals:
            errors.append(
                f"{REF_KEY} MUST be a Jinja expression (e.g. "
                f'`"{{{{ MYAPP_REF }}}}"`), not an inline literal:\n'
                + "\n".join(
                    f"  - {path}: {val!r}" for path, val in sorted(ref_literals)
                )
            )
        if missing_ref:
            errors.append(
                f"{URL_KEY} is set but {REF_KEY} is missing in the same "
                "dict — pinning the clone URL without the ref leaves the "
                "checkout at upstream HEAD (non-reproducible deploys):\n"
                + "\n".join(
                    f"  - {path}: url={val!r}" for path, val in sorted(missing_ref)
                )
            )

        if errors:
            self.fail("\n\n".join(errors))


if __name__ == "__main__":
    unittest.main()
