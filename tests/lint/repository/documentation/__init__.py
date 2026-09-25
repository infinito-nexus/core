from pathlib import Path

from tests.lint.repository import PROJECT_ROOT

INDEX_FILES = ("index.rst", "index.md", "README.md", "README.rst")

__all__ = ["INDEX_FILES", "PROJECT_ROOT", "index_page"]


def index_page(directory: Path) -> Path | None:
    """Return the page that stands in for ``directory``, None when it has none.

    Sphinx has no document for a folder, so a link to one resolves only through
    the page inside it. ``index`` comes before ``README`` because
    ``local.file_headings`` hides README.md from a directory carrying an
    index.rst.

    Args:
        directory: the directory a link or a code span points at.
    """
    for name in INDEX_FILES:
        candidate = directory / name
        if candidate.is_file():
            return candidate
    return None
