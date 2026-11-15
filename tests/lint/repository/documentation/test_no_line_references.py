import re
import unittest
from pathlib import Path

from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT, markdown_files

NUMBERS = r"\d+(?:-\d+)?(?:,\s?\d+(?:-\d+)?)*"
TICKED = re.compile(
    rf"`([^`\s:]+\.[A-Za-z][\w.]*|Makefile|Dockerfile[\w.-]*):({NUMBERS})`"
)
PLAIN = re.compile(
    rf"(?<![`\w/:.-])((?:\.\./)*(?:roles|tests|utils|scripts|plugins|cli|group_vars"
    rf"|docs|compose|playbook|filter_plugins|lookup_plugins|module_utils)/"
    rf"[\w./@+-]+\.[A-Za-z]\w*):({NUMBERS})"
)
LOCAL_ANCHOR = re.compile(r"\]\((?!https?:)([^)\s#]+)#L\d+(?:-L\d+)?\)")


def repository_files():
    """Returns:
    The relative paths and the base names of every file the repository holds.
    """
    paths = {
        Path(raw).relative_to(PROJECT_ROOT).as_posix()
        for raw in iter_non_ignored_files()
    }
    return paths, {Path(path).name for path in paths}


def in_repository(reference, page, paths, names):
    """Args:
    reference: the path a page cites.
    page: the page that cites it.
    paths: see :func:`repository_files`.
    names: see :func:`repository_files`.

    Returns:
        True when the reference names a file of this repository.
    """
    if reference in paths or Path(reference).name in names:
        return True
    resolved = (page.parent / reference).resolve()
    return resolved.is_relative_to(PROJECT_ROOT) and (
        resolved.relative_to(PROJECT_ROOT).as_posix() in paths
    )


def line_references(page, text, paths, names):
    """Args:
    page: the markdown page.
    text: its content.
    paths: see :func:`repository_files`.
    names: see :func:`repository_files`.

    Returns:
        ``line: reference`` for every line number or ``#L`` anchor the page
        attaches to a file of this repository.
    """
    return [
        f"{number}: {match.group(0)}"
        for number, line in enumerate(text.splitlines(), 1)
        for pattern in (TICKED, PLAIN, LOCAL_ANCHOR)
        for match in pattern.finditer(line)
        if in_repository(match.group(1), page, paths, names)
    ]


class TestNoLineReferences(unittest.TestCase):
    def test_markdown_cites_files_without_lines(self):
        paths, names = repository_files()
        offenders = [
            f"{page.relative_to(PROJECT_ROOT)}:{hit}"
            for page in markdown_files()
            for hit in line_references(page, read_text(str(page)), paths, names)
        ]
        self.assertEqual(
            offenders,
            [],
            "A markdown reference to a file of this repository names the file, "
            "never a line: drop the :N suffix or the #L anchor and name the "
            "test, function, task or key instead (docs/contributing/documentation.md):\n"
            + "\n".join(offenders),
        )

    def test_negative_control_each_form_is_caught(self):
        paths, names = repository_files()
        page = PROJECT_ROOT / "docs" / "contributing" / "planted.md"
        planted = (
            "`roles/web-svc-seaweedfs/tasks/00_core.yml:12`, "
            "roles/web-svc-seaweedfs/README.md:3-4 and "
            "[seaweedfs](../../roles/web-svc-seaweedfs/README.md#L5)"
        )
        self.assertEqual(len(line_references(page, planted, paths, names)), 3)

    def test_ports_and_upstream_files_pass(self):
        paths, names = repository_files()
        page = PROJECT_ROOT / "docs" / "contributing" / "planted.md"
        text = (
            "vhosts serve `:80`, `localhost:8080`, `example.com:443`, "
            "`RealmAdminResource.java:871-875` and "
            "[upstream](https://github.com/keycloak/keycloak/blob/26.8.2/x.java#L1)"
        )
        self.assertEqual(line_references(page, text, paths, names), [])


if __name__ == "__main__":
    unittest.main()
