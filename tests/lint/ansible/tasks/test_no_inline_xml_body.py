"""Forbid inline XML bodies in Ansible ``uri`` / ``uri_retry`` / ``ansible.builtin.uri`` tasks.

Extract every XML payload to a sibling file under the role and load
it via one of:

- ``templates/xml/<name>.xml.j2`` + ``body: "{{ lookup('template',
  'xml/<name>.xml.j2') }}"`` when the XML embeds Jinja variables.
- ``files/xml/<name>.xml`` + ``body: "{{ lookup('file',
  'xml/<name>.xml') }}"`` when the XML is fully static (no variable
  substitution, no ``{% raw %}`` escaping needed).

Inline XML blocks are harder to debug (no separate-file diff, no
editor XML support, hidden indentation rules between Ansible YAML
and Jinja), harder to lint, and they bloat the task file.

Detection: a ``body: |`` (or ``body: >``) folded/literal scalar whose
first content line starts with ``<``. JSON / shell / SQL bodies stay
allowed.

Per-line opt-out: ``# nocheck: inline-xml-body`` on the ``body:`` line
or the line above. Use only when the XML is genuinely so tiny and
context-bound that a separate file would obscure intent.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_SCAN_DIRS = ("roles", "tasks")
_SCAN_PREFIXES = tuple(f"{d}/" for d in _SCAN_DIRS)
_SCAN_SUFFIXES = (".yml", ".yaml")

_NOCHECK_RULE = "inline-xml-body"

_BODY_BLOCK_RE = re.compile(r"^(?P<indent>\s*)body:\s*[|>][+-]?\s*$")


def _iter_target_files():
    for abs_path in iter_project_files(extensions=_SCAN_SUFFIXES):
        rel = Path(abs_path).relative_to(PROJECT_ROOT).as_posix()
        if any(rel.startswith(p) for p in _SCAN_PREFIXES):
            yield Path(abs_path)


def _first_content_line_starts_with_xml(
    lines: list[str], body_idx: int, body_indent: int
) -> bool:
    """Look at the first non-blank child line of the body block."""
    inner_indent = body_indent + 1
    for i in range(body_idx + 1, len(lines)):
        line = lines[i]
        if not line.strip():
            continue
        line_indent = len(line) - len(line.lstrip())
        if line_indent <= body_indent:
            return False
        if line_indent < inner_indent:
            return False
        return line.lstrip().startswith("<")
    return False


def _scan_file(path: Path) -> list[tuple[int, str]]:
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []
    lines = text.splitlines()
    out: list[tuple[int, str]] = []
    for idx, line in enumerate(lines, start=1):
        match = _BODY_BLOCK_RE.match(line)
        if not match:
            continue
        body_indent = len(match.group("indent"))
        if not _first_content_line_starts_with_xml(lines, idx - 1, body_indent):
            continue
        if is_suppressed_at(lines, idx, _NOCHECK_RULE, mode="same-or-above"):
            continue
        out.append((idx, line.strip()))
    return out


class TestNoInlineXmlBody(unittest.TestCase):
    def test_scanner_matches_xml_body(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".yml", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(
                "- name: probe\n"
                "  uri:\n"
                "    url: http://x\n"
                "    method: POST\n"
                "    body: |\n"
                "      <page><title>X</title></page>\n"
            )
            fh.flush()
            hits = _scan_file(Path(fh.name))
        self.assertEqual(len(hits), 1)

    def test_scanner_ignores_non_xml_body(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".yml", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(
                "- name: probe\n"
                "  uri:\n"
                "    url: http://x\n"
                "    method: POST\n"
                "    body: |\n"
                '      {"key": "value"}\n'
            )
            fh.flush()
            hits = _scan_file(Path(fh.name))
        self.assertEqual(hits, [])

    def test_scanner_honours_same_line_nocheck(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".yml", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(
                "- name: probe\n"
                "  uri:\n"
                "    url: http://x\n"
                "    method: POST\n"
                "    body: |  # nocheck: inline-xml-body\n"
                "      <page><title>X</title></page>\n"
            )
            fh.flush()
            hits = _scan_file(Path(fh.name))
        self.assertEqual(hits, [])

    def test_scanner_honours_line_above_nocheck(self) -> None:
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".yml", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(
                "- name: probe\n"
                "  uri:\n"
                "    url: http://x\n"
                "    method: POST\n"
                "    # nocheck: inline-xml-body\n"
                "    body: |\n"
                "      <page><title>X</title></page>\n"
            )
            fh.flush()
            hits = _scan_file(Path(fh.name))
        self.assertEqual(hits, [])

    def test_no_inline_xml_bodies(self) -> None:
        offenders: dict[Path, list[tuple[int, str]]] = {}
        for path in _iter_target_files():
            hits = _scan_file(path)
            if hits:
                offenders[path] = hits

        if not offenders:
            return

        msg = [
            f"{sum(len(v) for v in offenders.values())} task(s) keep their XML "
            "payload inline. Extract to <role>/templates/xml/<name>.xml.j2 "
            "(when the XML embeds Jinja) and load with "
            "`body: \"{{ lookup('template', 'xml/<name>.xml.j2') }}\"`, OR "
            "to <role>/files/xml/<name>.xml (fully static) and load with "
            "`body: \"{{ lookup('file', 'xml/<name>.xml') }}\"`:",
            "",
        ]
        for path, hits in sorted(offenders.items()):
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            msg.append(f"  - {rel}:")
            for line_no, snippet in hits:
                msg.append(f"      {line_no}: {snippet}")
        msg.append("")
        msg.append(
            "Opt out per task with `# nocheck: inline-xml-body` on the body line "
            "or the line above only when the XML is so tiny and context-bound "
            "that a separate file would obscure intent."
        )
        self.fail("\n".join(msg))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
