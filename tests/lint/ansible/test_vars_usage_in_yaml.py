import unittest
from pathlib import Path
import re
from typing import Any, Iterable, Set, List, Dict, Tuple
import yaml

from utils.cache.files import iter_project_files, read_text


def repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise AssertionError("Repository root not found from test path.")


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

    REPO_ROOT = repo_root()
    YAML_EXTENSIONS = {".yml", ".yaml"}
    JINJA_EXTENSIONS = {".j2"}

    # Inventories are data-only bundle definitions (not tasks/templates) and can legitimately
    # contain vars that are not referenced inside Jinja blocks or Ansible expressions.
    # Therefore they are excluded from this lint.
    EXCLUDED_TOP_LEVEL_DIRS = {"inventories"}

    # ---------- File iteration & YAML loading ----------

    def _iter_files(self, extensions: set[str]) -> Iterable[Path]:
        exts = tuple(extensions)
        for path_str in iter_project_files(
            extensions=exts,
            exclude_dirs=tuple(self.EXCLUDED_TOP_LEVEL_DIRS),
        ):
            yield Path(path_str)

    def _load_yaml_documents(self, path: Path) -> List[Any]:
        try:
            return list(yaml.safe_load_all(read_text(str(path)))) or []
        except Exception:
            # File may contain heavy templating or anchors; skip structural parse
            return []

    def _walk_mapping(self, node: Any) -> Iterable[dict]:
        if isinstance(node, dict):
            yield node
            for v in node.values():
                yield from self._walk_mapping(v)
        elif isinstance(node, list):
            for item in node:
                yield from self._walk_mapping(item)

    # ---------- Collect vars passed via `vars:` (with locations) ----------

    def _collect_vars_passed_with_locations(
        self,
    ) -> Tuple[Set[str], Dict[str, Set[Tuple[Path, int]]]]:
        """
        Returns:
          - a set of all var names passed via `vars:`
          - a mapping var_name -> set of (path, line_number) where that var is defined under a vars: block

        Line numbers are best-effort based on raw text scanning (not YAML AST),
        because PyYAML doesn't preserve line info.
        """
        collected: Set[str] = set()
        locations: Dict[str, Set[Tuple[Path, int]]] = {}

        # Regex-based scan for:
        #   <indent>vars:
        #     <more-indent>key:
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

                    # allow blank lines inside vars block
                    if not line.strip():
                        i += 1
                        continue

                    indent = len(line) - len(line.lstrip(" "))
                    # end of vars block when indentation drops back
                    if indent <= base_indent:
                        break

                    km = key_re.match(line)
                    if km:
                        key = km.group(2).strip()
                        if key:
                            collected.add(key)
                            locations.setdefault(key, set()).add(
                                (yml, i + 1)
                            )  # 1-based line number
                    i += 1

        return collected, locations

    # ---------- Gather text for Jinja usage scanning ----------

    def _concat_texts(self) -> str:
        parts: List[str] = []
        for f in self._iter_files(self.YAML_EXTENSIONS | self.JINJA_EXTENSIONS):
            try:
                parts.append(read_text(str(f)))
            except Exception:
                # Non-UTF8 or unreadable — ignore
                pass
        return "\n".join(parts)

    # ---------- Extract Ansible expression strings from YAML ----------

    def _collect_ansible_expressions(self) -> List[str]:
        """
        Return a flat list of strings taken from Ansible expression-bearing fields:
        - when: <str> or when: [<str>, <str>, ...]
        - loop: <str>
        - with_*: <str>
        """
        exprs: List[str] = []
        for yml in self._iter_files(self.YAML_EXTENSIONS):
            docs = self._load_yaml_documents(yml)
            for doc in docs:
                for mapping in self._walk_mapping(doc):
                    for key, val in list(mapping.items()):
                        if key == "when":
                            if isinstance(val, str):
                                exprs.append(val)
                            elif isinstance(val, list):
                                exprs.extend([x for x in val if isinstance(x, str)])
                        elif key == "loop":
                            if isinstance(val, str):
                                exprs.append(val)
                        elif isinstance(key, str) and key.startswith("with_"):
                            if isinstance(val, str):
                                exprs.append(val)
        return exprs

    # ---------- Usage checks ----------

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

    def _used_in_ansible_exprs(self, var_name: str, exprs: List[str]) -> bool:
        """
        Detect var usage in Ansible expressions (when/loop/with_*),
        excluding function/macro calls like `var_name(...)`.
        """
        pat = re.compile(r"\b" + re.escape(var_name) + r"\b(?!\s*\()")
        return any(pat.search(e) for e in exprs)

    # ---------- Test ----------

    def test_vars_passed_are_used_in_yaml_or_jinja(self):
        vars_passed, vars_locations = self._collect_vars_passed_with_locations()
        self.assertTrue(
            vars_passed,
            "No variables passed via `vars:` were found. "
            "Check the repo root path in this test.",
        )

        all_text = self._concat_texts()
        ansible_exprs = self._collect_ansible_expressions()

        unused: List[str] = []
        for var_name in sorted(vars_passed):
            used = self._used_in_jinja_blocks(
                var_name, all_text
            ) or self._used_in_ansible_exprs(var_name, ansible_exprs)
            if not used:
                if var_name not in ["ansible_python_interpreter"]:
                    unused.append(var_name)

        if unused:
            lines: List[str] = []
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
                        rel = path.relative_to(self.REPO_ROOT)
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
