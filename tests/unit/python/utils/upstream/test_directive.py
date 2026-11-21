"""Unit tests for the ``upstream:`` directive grammar, URL classifier and scan."""

from __future__ import annotations

import unittest
import unittest.mock as mock
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.lint.repository import test_comments_valid as comments
from utils.upstream import directive
from utils.upstream.directive import (
    GITEA,
    GITHUB,
    GITLAB,
    ISSUE,
    PULL,
    Directive,
    Reference,
    classify,
    directives_in,
    opens_directive,
)

HASH = "#"
GH_HOST = "github.com"
GH = f"https://{GH_HOST}"
GH_PLAIN = "http://github.com"
GL = "https://gitlab.com"
CB = "https://codeberg.org"
GT = "https://gitea.com"
ISSUE_URL = f"{GH}/owner/repo/issues/7"
SYNTAXES = (("#", ""), ("//", ""), ("/*", " */"), ("{#", " #}"), ("<!--", " -->"))


def _directive_line(opener: str, text: str, closer: str) -> str:
    """One comment line carrying *text* as a directive.

    Args:
        opener: the comment prefix.
        text: what follows the keyword.
        closer: the comment closer, ``""`` for a line comment.
    """
    return f"{opener} upstream: {text}{closer}"


class TestDirectivesIn(unittest.TestCase):
    def test_every_comment_syntax_is_read(self) -> None:
        for opener, closer in SYNTAXES:
            with self.subTest(opener=opener):
                lines = ["value: 1", _directive_line(opener, ISSUE_URL, closer)]
                self.assertEqual(
                    directives_in("file.txt", lines),
                    [Directive("file.txt", 2, ISSUE_URL)],
                )

    def test_a_trailing_comment_after_code_is_read(self) -> None:
        lines = [f"version: 1.2.3  {HASH} upstream: {ISSUE_URL}"]
        self.assertEqual(
            directives_in("meta.yml", lines), [Directive("meta.yml", 1, ISSUE_URL)]
        )

    def test_a_prefix_quoted_in_a_string_or_code_span_is_no_directive(self) -> None:
        lines = [
            f'line = "{HASH} upstream: {ISSUE_URL}"',
            f"Write `{HASH} upstream: <url>` above the workaround.",
        ]
        self.assertEqual(directives_in("docs.md", lines), [])

    def test_a_yaml_key_named_upstream_is_no_directive(self) -> None:
        lines = [f"      upstream: {GH}/"]
        self.assertEqual(directives_in("networks.yml", lines), [])

    def test_a_patch_takes_the_bare_form_above_its_first_diff_header(self) -> None:
        lines = [
            "Explains the patch.",
            f"upstream: {ISSUE_URL}",
            "--- a/main.go",
            "+++ b/main.go",
            f"upstream: {ISSUE_URL}",
        ]
        self.assertEqual(
            directives_in("fix.patch", lines), [Directive("fix.patch", 2, ISSUE_URL)]
        )

    def test_the_bare_form_outside_a_patch_is_no_directive(self) -> None:
        self.assertEqual(directives_in("notes.md", [f"upstream: {ISSUE_URL}"]), [])

    def test_text_after_the_url_stays_in_the_directive(self) -> None:
        text = f"{ISSUE_URL} fixed in 2.0"
        found = directives_in("file.sh", [_directive_line("#", text, "")])
        self.assertEqual(found, [Directive("file.sh", 1, text)])
        self.assertIsNone(classify(found[0].text))


class TestClassify(unittest.TestCase):
    def test_every_forge_shape_is_read(self) -> None:
        cases = {
            f"{GH}/owner/repo/issues/7": Reference(
                GITHUB, "github.com", "owner/repo", ISSUE, 7
            ),
            f"{GH}/owner/repo/pull/8#issuecomment-1": Reference(
                GITHUB, "github.com", "owner/repo", PULL, 8
            ),
            f"{GL}/group/sub/project/-/issues/9": Reference(
                GITLAB, "gitlab.com", "group/sub/project", ISSUE, 9
            ),
            f"{GL}/group/project/-/merge_requests/10": Reference(
                GITLAB, "gitlab.com", "group/project", PULL, 10
            ),
            "https://gitlab.example/team/app/-/issues/11": Reference(
                GITLAB, "gitlab.example", "team/app", ISSUE, 11
            ),
            f"{CB}/owner/repo/pulls/12": Reference(
                GITEA, "codeberg.org", "owner/repo", PULL, 12
            ),
            f"{GT}/owner/repo/issues/13": Reference(
                GITEA, "gitea.com", "owner/repo", ISSUE, 13
            ),
            "https://git.example/owner/.github/issues/14": Reference(
                GITEA, "git.example", "owner/.github", ISSUE, 14
            ),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(classify(text), expected)

    def test_every_other_shape_is_rejected(self) -> None:
        for text in (
            "",
            "see the upstream tracker",
            f"{GH}/owner/repo/issues/7 {GH}/owner/repo/issues/8",
            f"{GH_PLAIN}/owner/repo/issues/7",
            f"{GH}/owner/repo/pulls/7",
            f"{GH}/owner/repo/issues/0",
            f"{GH}/owner/repo/issues",
            f"{GH}/owner/repo/issues/7?page=2",
            f"{GH}/owner/repo/pull/7/files",
            f"{GH}/owner/repo/-/issues/7",
            f"https://user@{GH_HOST}/owner/repo/issues/7",
            f"{GL}/group/project/issues/7",
            f"{GL}/project/-/issues/7",
            "https://git.example/project/-/issues/7",
            f"{CB}/owner/repo/pull/7",
            f"{CB}:8443/owner/repo/issues/7",
            "https://bugs.launchpad.invalid/ubuntu/+bug/7",
        ):
            with self.subTest(text=text):
                self.assertIsNone(classify(text))


class TestOpensDirective(unittest.TestCase):
    def test_only_a_body_that_starts_with_the_keyword_is_a_directive(self) -> None:
        self.assertTrue(opens_directive(f"upstream: {ISSUE_URL}"))
        self.assertFalse(opens_directive(f"see upstream: {ISSUE_URL}"))
        self.assertFalse(opens_directive(f"Upstream: {ISSUE_URL}"))


class TestRepositoryDirectives(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        line = _directive_line("#", ISSUE_URL, "")
        (self.root / "locale" / "de").mkdir(parents=True)
        (self.root / "task.yml").write_text(f"key: 1\n{line}\n", encoding="utf-8")
        (self.root / "locale" / "de" / "docs.po").write_text(
            f"{line}\n", encoding="utf-8"
        )
        (self.root / "blob.bin").write_bytes(b"\0" + line.encode())
        (self.root / "plain.txt").write_text("nothing here\n", encoding="utf-8")
        listed = ("blob.bin", "gone.txt", "locale/de/docs.po", "plain.txt", "task.yml")
        for name, value in (
            ("PROJECT_ROOT", self.root),
            ("repository_files", mock.Mock(return_value=listed)),
        ):
            patcher = mock.patch.object(directive, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_only_listed_text_files_outside_locale_are_read(self) -> None:
        self.assertEqual(
            directive.repository_directives(), [Directive("task.yml", 2, ISSUE_URL)]
        )


class TestCommentLintAcceptsTheDirective(unittest.TestCase):
    def test_the_directive_passes_where_narration_is_flagged(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "tasks.yml"
            path.write_text(
                "\n".join(
                    [
                        "- name: first",
                        "  debug:",
                        _directive_line("#", ISSUE_URL, ""),
                        "- name: second",
                        f"{HASH} narration that explains nothing",
                        "- name: third",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                comments.find_invalid_comments(path),
                [(5, "narration that explains nothing")],
            )


if __name__ == "__main__":
    unittest.main()
