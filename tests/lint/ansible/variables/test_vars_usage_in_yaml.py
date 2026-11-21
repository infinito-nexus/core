import contextlib
import re
import unittest
from collections.abc import Iterable
from pathlib import Path
from typing import Any, ClassVar

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_all

from . import PROJECT_ROOT


class TestVarsPassedAreUsed(unittest.TestCase):
    """
    Integration test:
    - Walk all *.yml/*.yaml and *.j2 files
    - Collect variable names passed via task-level `vars:`
      AND remember where they were defined (file + line)
    - Consider a var "used" if it appears in ANY of:
        • Jinja output blocks:     {{ ... var_name ... }}
        • Jinja statement blocks:  {% ... var_name ... %}
        • Ansible expressions in YAML:
            - when: <expr>          (string or list of strings)
            - loop: <expr>
            - with_*: <expr>

    Additional rule:
    - Do NOT count as used if the token is immediately followed by '(' (optionally with whitespace),
      i.e. treat `var_name(` as a function/macro call, not a variable usage.
    """

    YAML_EXTENSIONS: ClassVar[set[str]] = {".yml", ".yaml"}
    JINJA_EXTENSIONS: ClassVar[set[str]] = {".j2"}

    EXCLUDED_TOP_LEVEL_DIRS: ClassVar[set[str]] = {"inventories"}

    def _iter_files(self, extensions: set[str]) -> Iterable[Path]:
        exts = tuple(extensions)
        for path_str in iter_project_files(
            extensions=exts,
            exclude_dirs=tuple(self.EXCLUDED_TOP_LEVEL_DIRS),
        ):
            yield Path(path_str)

    def _load_yaml_documents(self, path: Path) -> list[Any]:
        try:
            return list(load_yaml_all(path, default_if_missing=()))
        except Exception:
            return []

    def _walk_mapping(self, node: Any) -> Iterable[dict]:
        if isinstance(node, dict):
            yield node
            for v in node.values():
                yield from self._walk_mapping(v)
        elif isinstance(node, list):
            for item in node:
                yield from self._walk_mapping(item)

    def _collect_vars_passed_with_locations(
        self,
    ) -> tuple[set[str], dict[str, set[tuple[Path, int]]]]:
        """
        Returns:
          - a set of all var names passed via `vars:`
          - a mapping var_name -> set of (path, line_number) where that var is defined under a vars: block

        Line numbers are best-effort based on raw text scanning (not YAML AST),
        because PyYAML doesn't preserve line info.

        Only the first key level under ``vars:`` is a variable. Anything deeper
        belongs to that variable's value -- ``role_templates`` is passed, the
        ``dest_dir`` of its list items is data -- and counting those as
        variables demands they appear in a Jinja block of their own, which a
        consumer written in Python never provides.
        """
        collected: set[str] = set()
        locations: dict[str, set[tuple[Path, int]]] = {}

        vars_block_re = re.compile(r"^(\s*)vars:\s*$")
        key_re = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:")

        for yml in self._iter_files(self.YAML_EXTENSIONS):
            try:
                lines = read_text(str(yml)).splitlines()
            except Exception:
                continue

            i = 0
            while i < len(lines):
                m = vars_block_re.match(lines[i])
                if not m:
                    i += 1
                    continue

                base_indent = len(m.group(1))
                var_indent: int | None = None
                i += 1

                while i < len(lines):
                    line = lines[i]

                    if not line.strip():
                        i += 1
                        continue

                    indent = len(line) - len(line.lstrip(" "))
                    if indent <= base_indent:
                        break

                    km = key_re.match(line)
                    if km:
                        if var_indent is None:
                            var_indent = indent
                        key = km.group(2).strip()
                        if key and indent == var_indent:
                            collected.add(key)
                            locations.setdefault(key, set()).add((yml, i + 1))
                    i += 1

        return collected, locations

    def _concat_texts(self) -> str:
        parts: list[str] = []
        for f in self._iter_files(self.YAML_EXTENSIONS | self.JINJA_EXTENSIONS):
            with contextlib.suppress(Exception):
                parts.append(read_text(str(f)))
        return "\n".join(parts)

    def _collect_ansible_expressions(self) -> list[str]:
        """
        Return a flat list of strings taken from Ansible expression-bearing fields:
        - when / failed_when / changed_when / until / that: <str> or [<str>, ...]
        - loop: <str>
        - with_*: <str>
        """
        exprs: list[str] = []
        for yml in self._iter_files(self.YAML_EXTENSIONS):
            docs = self._load_yaml_documents(yml)
            for doc in docs:
                for mapping in self._walk_mapping(doc):
                    for key, val in list(mapping.items()):
                        if key in (
                            "when",
                            "failed_when",
                            "changed_when",
                            "until",
                            "that",
                        ):
                            if isinstance(val, str):
                                exprs.append(val)
                            elif isinstance(val, list):
                                exprs.extend([x for x in val if isinstance(x, str)])
                        elif (
                            key == "loop"
                            or (isinstance(key, str) and key.startswith("with_"))
                        ) and isinstance(val, str):
                            exprs.append(val)
        return exprs

    USED_TOKEN: ClassVar[re.Pattern[str]] = re.compile(r"\b(\w+)\b(?!\s*\()")
    BLOCK_SEPARATOR: ClassVar[str] = "\x00"

    @staticmethod
    def _block_bodies(text: str, opener: str, closer: str) -> Iterable[str]:
        """
        Args:
            text: the concatenated YAML and Jinja sources.
            opener: ``{{`` or ``{%``.
            closer: ``}}`` or ``%}``.

        Yields:
            The text between each opener and the first closer after it.
        """
        start = text.find(opener)
        while start != -1:
            end = text.find(closer, start + len(opener))
            if end == -1:
                return
            yield text[start + len(opener) : end]
            start = text.find(opener, end - 1)

    def _tokens_used_in_jinja_blocks(self, text: str) -> set[str]:
        """
        Every token used inside a Jinja block, excluding function/macro calls
        like `var_name(...)`: a block runs from its opener to the first closer
        after it, and a token followed by `(` does not count.

        Args:
            text: the concatenated YAML and Jinja sources.
        """
        bodies = self.BLOCK_SEPARATOR.join(
            body
            for opener, closer in (("{{", "}}"), ("{%", "%}"))
            for body in self._block_bodies(text, opener, closer)
        )
        return set(self.USED_TOKEN.findall(bodies))

    def _tokens_used_in_ansible_exprs(self, exprs: list[str]) -> set[str]:
        """
        Every token used in an Ansible expression (when/loop/with_*),
        excluding function/macro calls like `var_name(...)`.

        Args:
            exprs: the expression strings of the YAML files.
        """
        return set(self.USED_TOKEN.findall(self.BLOCK_SEPARATOR.join(exprs)))

    def test_vars_passed_are_used_in_yaml_or_jinja(self):
        vars_passed, vars_locations = self._collect_vars_passed_with_locations()
        self.assertTrue(
            vars_passed,
            "No variables passed via `vars:` were found. "
            "Check the repo root path in this test.",
        )

        used_tokens = self._tokens_used_in_jinja_blocks(
            self._concat_texts()
        ) | self._tokens_used_in_ansible_exprs(self._collect_ansible_expressions())

        unused: list[str] = []
        for var_name in sorted(vars_passed):
            used = var_name in used_tokens
            if not used and var_name != "ansible_python_interpreter":
                unused.append(var_name)

        if unused:
            lines: list[str] = []
            lines.append(
                "The following variables are passed via `vars:` but never referenced in:\n"
                "  • Jinja output/statement blocks ({{ ... }} / {% ... %}) OR\n"
                "  • Ansible expressions (when/loop/with_*)\n"
            )

            for v in unused:
                lines.append(f"- {v}")
                locs = sorted(
                    vars_locations.get(v, set()),
                    key=lambda t: (str(t[0]), t[1]),
                )
                if locs:
                    for path, lineno in locs:
                        rel = path.relative_to(PROJECT_ROOT)
                        lines.append(f"    • {rel}:{lineno}")
                else:
                    lines.append("    • (location unknown)")

            lines.append(
                "\nNotes:\n"
                " • Function-like tokens (name followed by '(') are ignored intentionally.\n"
                " • If a var is only used in Python code or other file types, extend the test accordingly\n"
                "   or remove the var if it's truly unused."
            )
            self.fail("\n".join(lines))
