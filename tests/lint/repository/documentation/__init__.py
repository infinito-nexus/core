from pathlib import Path

from utils.cache.files import iter_non_ignored_files

from tests.lint.repository import PROJECT_ROOT

INDEX_FILES = ("index.rst", "index.md", "README.md", "README.rst")

__all__ = ["INDEX_FILES", "PROJECT_ROOT", "index_page", "markdown_files"]


AGENT_STATE = (".agents", ".claude")


def markdown_files() -> list[Path]:
    """Return every ``.md`` file of the repository the lints are meant to read.

    Exception: asking ``git ls-files`` would answer a different question -- it
    lists what is tracked, so a tracked file inside an ignored directory counts
    and an untracked one never does. It also refuses the worktree the test
    container mounts, which would make the two environments lint two different
    file sets.

    Exception: the agent state directories are dropped explicitly, because
    ``iter_non_ignored_files`` reads only the root ``.gitignore`` and misses
    the nested one that ignores them. On the host the sandbox mounts
    ``/dev/null`` over entries there, so what is enumerated is a character
    device rather than a page. ``.markdownlint-cli2.jsonc`` excludes the same
    two trees.
    """
    return [
        path
        for raw in iter_non_ignored_files(extensions=(".md",))
        if not set(AGENT_STATE) & set((path := Path(raw)).relative_to(PROJECT_ROOT).parts)
    ]


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
