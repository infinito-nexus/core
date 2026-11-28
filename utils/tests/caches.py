from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from utils.cache.reset import _reset_cache_for_tests, _reset_rendered_caches_for_tests

if TYPE_CHECKING:
    from collections.abc import Iterator


def reset_caches(*, files_changed: bool) -> None:
    """
    Args:
        files_changed: True when the test writes, edits or fakes a file the
            parsed file, YAML or role-defaults caches could hold (a temp role
            tree, a patched loader): every cache goes. False when the test
            only reads the source tree and varies its inputs (inventory,
            group names, templar, patched renderers): the parsed files and
            role defaults stay warm and only the rendered layers (merged
            applications, users, domains, domain index) go.
    """
    if files_changed:
        _reset_cache_for_tests()
    else:
        _reset_rendered_caches_for_tests()


@contextmanager
def fresh_caches(*, files_changed: bool) -> Iterator[None]:
    """
    Args:
        files_changed: forwarded to both ``reset_caches`` calls.
    """
    reset_caches(files_changed=files_changed)
    try:
        yield
    finally:
        reset_caches(files_changed=files_changed)
