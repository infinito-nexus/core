"""Lint guard: every ``version:`` value paired with an ``image:`` key and
every ``ref:`` value paired with a ``repository:`` key inside a
``meta/services.yml`` SHOULD be semver-compatible.

Why
---

Semver pinning is the precondition for the daily auto-update job at
[update-image-versions](../../../../.github/workflows/update.yml) and
[update-repository-refs](../../../../.github/workflows/update.yml):
those jobs only bump entries whose current value matches the semver
shape (``v?\\d+(\\.\\d+){0,3}(-flavor)?``). A pin like ``latest``,
``stable``, ``master``, ``main``, or a commit SHA silently opts the
entry out of the freshness pipeline. That MAY be intentional (e.g. a
vendor image that does not publish semver tags, or a plugin tracked
against ``master``), but it MUST be explicit so freshness coverage
stays auditable.

Warn-only
---------

This check is **warn-only**: it never fails the test session. Each
unmarked non-semver pin surfaces twice: once via :mod:`warnings`
(pytest "warnings summary"), once via a GitHub Actions
``::warning file=...,line=...::...`` annotation (PR-side yellow
marker). Suppression removes the entry from both surfaces.

Suppression
-----------

Per-line opt-out via ``# nocheck:`` on the same line as the pin key
or on the immediately preceding non-empty line:

* ``# nocheck: docker-version`` above (or on) a ``version:`` line for
  intentional non-semver image pins. Same marker as the daily
  external check at
  [test_image_versions.py](../../../../external/update/docker/test_image_versions.py).
* ``# nocheck: repository-version`` above (or on) a ``ref:`` line for
  intentional non-semver git ref pins. Same marker as the daily
  external check at
  [test_repository_versions.py](../../../../external/update/repository/test_repository_versions.py).

Scope
-----

Recursive scan over every ``roles/*/meta/services.yml``. Both top-level
entities and nested sub-entities (plugin maps, list items) are
inspected.
"""

from __future__ import annotations

import unittest
import warnings
from typing import TYPE_CHECKING

from utils.annotations.message import in_github_actions
from utils.annotations.message import warning as gha_warning
from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.base import is_semver

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterator


_DOCKER_RULE = "docker-version"
_REPO_RULE = "repository-version"

_DOCKER_TITLE = "Non-semver Docker image version"
_REPO_TITLE = "Non-semver repository ref"


class NonSemverImageVersionWarning(UserWarning):
    """Warning category for non-semver ``image: <name>`` + ``version:`` pins."""


class NonSemverRepositoryRefWarning(UserWarning):
    """Warning category for non-semver ``repository: <url>`` + ``ref:`` pins."""


def _walk_pinned_pairs(
    node, path: tuple[str, ...]
) -> Iterator[tuple[str, tuple[str, ...], str, str]]:
    """Yield ``(kind, entity_path, lhs, value)`` for every dict that pairs
    ``image:`` + ``version:`` (kind=``image``) or ``repository:`` + ``ref:``
    (kind=``ref``). The walker recurses through nested dicts and lists so
    sub-entities and plugin maps are also covered."""
    if isinstance(node, dict):
        image = node.get("image")
        version = node.get("version")
        if isinstance(image, str) and image and isinstance(version, str) and version:
            yield ("image", path, image.strip(), version.strip())
        repo = node.get("repository")
        ref = node.get("ref")
        if isinstance(repo, str) and repo and isinstance(ref, str) and ref:
            yield ("ref", path, repo.strip(), ref.strip())
        for key, value in node.items():
            if key in ("image", "version", "repository", "ref"):
                continue
            yield from _walk_pinned_pairs(value, (*path, str(key)))
    elif isinstance(node, list):
        for index, item in enumerate(node):
            yield from _walk_pinned_pairs(item, (*path, f"[{index}]"))


def _locate_value_line(
    lines: list[str], key_name: str, target_value: str, used: set[int]
) -> int | None:
    """Return the 1-indexed line number of the first ``<key>: <target_value>``
    line whose extracted value matches ``target_value`` and that has not
    yet been consumed via ``used``."""
    for idx, raw_line in enumerate(lines, start=1):
        if idx in used:
            continue
        stripped = raw_line.strip()
        if not stripped.startswith(f"{key_name}:") and not stripped.startswith(
            f"{key_name} :"
        ):
            continue
        try:
            _, value = stripped.split(":", 1)
        except ValueError:
            continue
        value = value.split("#", 1)[0].strip().strip("'\"")
        if value == target_value:
            return idx
    return None


def _emit_warning(
    path_rel: str,
    line_no: int,
    body: str,
    title: str,
    category: type[Warning],
) -> None:
    msg = f"{path_rel}:{line_no}: {body}"
    warnings.warn(msg, category, stacklevel=2)
    if in_github_actions():
        gha_warning(body, title=title, file=path_rel, line=line_no)


class TestSemverPinning(unittest.TestCase):
    """Warn-only lint: surfaces non-semver ``version:`` and ``ref:`` pins."""

    def test_pinned_versions_and_refs_are_semver(self) -> None:
        roles_root = PROJECT_ROOT / "roles"
        if not roles_root.is_dir():
            return

        findings_emitted = False
        for role_dir in sorted(p for p in roles_root.iterdir() if p.is_dir()):
            config_path = role_dir / ROLE_FILE_META_SERVICES
            if not config_path.is_file():
                continue
            data = load_yaml_any(str(config_path), default_if_missing=None)
            if not isinstance(data, dict):
                continue

            raw = read_text(str(config_path))
            lines = raw.splitlines()
            rel = config_path.relative_to(PROJECT_ROOT).as_posix()
            used_version_lines: set[int] = set()
            used_ref_lines: set[int] = set()

            for kind, entity_path, lhs, value in _walk_pinned_pairs(data, ()):
                if is_semver(value):
                    continue

                if kind == "image":
                    line_no = _locate_value_line(
                        lines, "version", value, used_version_lines
                    )
                    rule = _DOCKER_RULE
                    title = _DOCKER_TITLE
                    category: type[Warning] = NonSemverImageVersionWarning
                    key_label = "version"
                else:
                    line_no = _locate_value_line(lines, "ref", value, used_ref_lines)
                    rule = _REPO_RULE
                    title = _REPO_TITLE
                    category = NonSemverRepositoryRefWarning
                    key_label = "ref"

                if line_no is None:
                    continue

                if kind == "image":
                    used_version_lines.add(line_no)
                else:
                    used_ref_lines.add(line_no)

                if is_suppressed_at(lines, line_no, rule):
                    continue

                entity = ".".join(entity_path) or "<root>"
                body = (
                    f"{role_dir.name}/{entity}: {lhs} is pinned at "
                    f"{key_label} '{value}' which is not semver-compatible."
                )
                _emit_warning(rel, line_no, body, title, category)
                findings_emitted = True

        if findings_emitted:
            print(
                "\n💡 Non-semver pins: suppress with "
                "'# nocheck: docker-version' (above or on the `version:` line) "
                "or '# nocheck: repository-version' (above or on the `ref:` "
                "line) when the non-semver pin is intentional.",
                flush=True,
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
