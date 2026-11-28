from functools import lru_cache
from pathlib import Path

from utils.cache.files import iter_non_ignored_files

PROJECT_ROOT: Path = Path(__file__).resolve().parents[4]

__all__ = ["PROJECT_ROOT", "files_outside_locale"]


@lru_cache(maxsize=1)
def files_outside_locale() -> tuple[tuple[str, str], ...]:
    """The non-ignored project files the removal guards scan, walked once per process.

    ``locale/`` is left out before any file is read, because the i18n
    extraction regenerates it from the documentation.

    Returns:
        ``(path relative to the project root, absolute path)`` per file.
    """
    return tuple(
        (rel, path)
        for path in iter_non_ignored_files()
        if not (rel := Path(path).relative_to(PROJECT_ROOT).as_posix()).startswith(
            "locale/"
        )
    )
