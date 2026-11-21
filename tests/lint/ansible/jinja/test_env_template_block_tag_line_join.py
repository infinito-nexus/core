from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT, is_env_template, is_service_env_template

_RULE = "env-template-line-join"

_TAG_RE = re.compile(r"\{%.*?%\}|\{#.*?#\}", re.DOTALL)


def _line_shapes(content: str) -> list[tuple[bool, bool]]:
    """Return per line whether it renders content and whether its newline is emitted.

    Args:
        content: the template text.

    Returns:
        One ``(has_content, newline_emitted)`` pair per line. Text inside a
        tag is no content; a newline inside a tag, or right after a block or
        comment tag that does not end in ``+%}``, is not emitted.
    """
    in_tag = bytearray(len(content))
    trimmed_newlines: set[int] = set()
    for tag in _TAG_RE.finditer(content):
        in_tag[tag.start() : tag.end()] = b"\x01" * (tag.end() - tag.start())
        if (
            not tag.group().endswith("+%}")
            and content[tag.end() : tag.end() + 1] == "\n"
        ):
            trimmed_newlines.add(tag.end())
    shapes: list[tuple[bool, bool]] = []
    start = 0
    for line in content.split("\n"):
        end = start + len(line)
        has_content = any(
            not in_tag[position] and not content[position].isspace()
            for position in range(start, end)
        )
        newline_emitted = (
            end < len(content) and not in_tag[end] and end not in trimmed_newlines
        )
        shapes.append((has_content, newline_emitted))
        start = end + 1
    return shapes


def glued_lines(content: str) -> dict[int, str]:
    """Map each line that ``trim_blocks`` glues to the next line with content.

    Args:
        content: the template text.

    Returns:
        ``{index: next_line}`` with the 0-based index of a line that renders
        content and emits no newline, and the stripped next line with content
        it is joined with; a blank or ``+%}`` line in between, or the end of
        the file, ends the scan without a finding.
    """
    lines = content.split("\n")
    shapes = _line_shapes(content)
    found: dict[int, str] = {}
    for index, (has_content, newline_emitted) in enumerate(shapes):
        if not has_content or newline_emitted:
            continue
        for following in range(index + 1, len(lines)):
            if shapes[following][0]:
                found[index] = lines[following].strip()
                break
            if shapes[following][1]:
                break
    return found


class TestEnvTemplateBlockTagLineJoin(unittest.TestCase):
    def glued(self, *lines: str) -> dict[int, str]:
        return glued_lines("\n".join(lines))

    def test_detects_the_join(self) -> None:
        self.assertEqual(
            self.glued("A=x{% if y %},z{% endif %}", "B=false"), {0: "B=false"}
        )

    def test_follows_tag_only_lines(self) -> None:
        self.assertEqual(
            self.glued(
                "{% if a %}",
                "A={% if y %}1{% else %}2{% endif %}",
                "{% endif %}",
                "B=1",
            ),
            {1: "B=1"},
        )

    def test_checks_a_line_that_starts_with_a_tag(self) -> None:
        self.assertEqual(self.glued("{% if x %}K=v{% endif %}", "B=1"), {0: "B=1"})

    def test_does_not_skip_a_tag_wrapped_content_line(self) -> None:
        self.assertEqual(
            self.glued("A={% if y %}1{% endif %}", "{% if z %}B=1{% endif %}"),
            {0: "{% if z %}B=1{% endif %}"},
        )

    def test_follows_a_tag_spanning_several_lines(self) -> None:
        self.assertEqual(
            self.glued("A=1{% set x = {", "  'a': 1,", "} %}", "B=2"), {0: "B=2"}
        )

    def test_a_tag_spanning_several_lines_on_its_own_is_safe(self) -> None:
        self.assertEqual(
            self.glued("A=1", "{% set x = {", "  'a': 1,", "}) %}", "B=2"), {}
        )

    def test_accepts_blank_line_end_of_file_and_expressions(self) -> None:
        self.assertEqual(
            self.glued("A={% if y %}1{% else %}2{% endif %}", "", "B=1"), {}
        )
        self.assertEqual(self.glued("A={% if y %}1{% endif %}", "{% endif %}"), {})
        self.assertEqual(self.glued("A=x{{ ',z' if y else '' }}", "B=1"), {})
        self.assertEqual(self.glued("A=x{% if y %},z{% endif +%}", "B=1"), {})
        self.assertEqual(
            self.glued("A={% if y %}1{% endif %}", "{% endif +%}", "B=1"), {}
        )
        self.assertEqual(self.glued("{% if y %}", "B=1"), {})

    def test_env_templates_do_not_glue_lines(self) -> None:
        findings: list[str] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not (is_env_template(rel) or is_service_env_template(rel)):
                continue
            lines = content.split("\n")
            for index, glued in sorted(glued_lines(content).items()):
                if is_suppressed_at(lines, index + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append(
                    f"- {rel}:{index + 1}: {lines[index].strip()}  <- glued to: {glued}"
                )

        if findings:
            self.fail(
                "Found env-template lines that end in a Jinja block tag and get glued "
                "to the next line (Ansible renders with trim_blocks, which eats the "
                "newline after the tag, so the next KEY= becomes part of this line).\n\n"
                "Fix: write the condition as an inline expression "
                "(KEY={{ 'b' if cond else 'a' }}), or leave a blank line after the "
                f"line. Mark a genuine exception with `# nocheck: {_RULE}`.\n\n"
                "Offending lines:\n" + "\n".join(sorted(findings))
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
