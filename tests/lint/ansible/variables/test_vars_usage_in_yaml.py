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
          (robust against inner '}' / '%' via tempered regex)
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
                        key = km.group(2).strip()
                        if key:
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
        - when / failed_when / changed_when / until: <str> or [<str>, ...]
        - loop: <str>
        - with_*: <str>
        """
        exprs: list[str] = []
        for yml in self._iter_files(self.YAML_EXTENSIONS):
            docs = self._load_yaml_documents(yml)
            for doc in docs:
                for mapping in self._walk_mapping(doc):
                    for key, val in list(mapping.items()):
                        if key in ("when", "failed_when", "changed_when", "until"):
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

    def _used_in_jinja_blocks(self, var_name: str, text: str) -> bool:
        """
        Detect var usage inside Jinja blocks, excluding function/macro calls like `var_name(...)`.
        We use a tempered regex to avoid stopping at the first '}}'/'%}' and a negative lookahead
        `(?!\\s*\\()` after the token.
        """
        token = r"\b" + re.escape(var_name) + r"\b(?!\s*\()"

        pat_output = re.compile(
            r"{{(?:(?!}}).)*" + token + r"(?:(?!}}).)*}}",
            re.DOTALL,
        )
        pat_stmt = re.compile(
            r"{%(?:(?!%}).)*" + token + r"(?:(?!%}).)*%}",
            re.DOTALL,
        )
        return pat_output.search(text) is not None or pat_stmt.search(text) is not None

    def _used_in_ansible_exprs(self, var_name: str, exprs: list[str]) -> bool:
        """
        Detect var usage in Ansible expressions (when/loop/with_*),
        excluding function/macro calls like `var_name(...)`.
        """
        pat = re.compile(r"\b" + re.escape(var_name) + r"\b(?!\s*\()")
        return any(pat.search(e) for e in exprs)

    def test_vars_passed_are_used_in_yaml_or_jinja(self):
        vars_passed, vars_locations = self._collect_vars_passed_with_locations()
        self.assertTrue(
            vars_passed,
            "No variables passed via `vars:` were found. "
            "Check the repo root path in this test.",
        )

        all_text = self._concat_texts()
        ansible_exprs = self._collect_ansible_expressions()

        unused: list[str] = []
        for var_name in sorted(vars_passed):
            used = self._used_in_jinja_blocks(
                var_name, all_text
            ) or self._used_in_ansible_exprs(var_name, ansible_exprs)
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
