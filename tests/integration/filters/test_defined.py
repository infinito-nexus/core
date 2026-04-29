# tests/integration/test_filters_are_defined.py
import ast
import os
import re
import unittest
from typing import Dict, List, Set, Tuple

from utils.cache.files import iter_project_files, read_text

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))

# EXCLUDES tests/ by default; keeps True to require real usage sites
EXCLUDE_TESTS = True

# File extensions to scan for template usage
USAGE_EXTS = (".yml", ".yaml", ".j2", ".jinja2", ".tmpl")

# Built-in / common filters that shouldn't require local definitions
BUILTIN_FILTERS: Set[str] = {
    # Jinja2 core/common
    "abs",
    "attr",
    "batch",
    "capitalize",
    "center",
    "default",
    "d",
    "dictsort",
    "escape",
    "e",
    "filesizeformat",
    "first",
    "float",
    "forceescape",
    "format",
    "groupby",
    "indent",
    "int",
    "join",
    "last",
    "length",
    "list",
    "lower",
    "map",
    "min",
    "max",
    "random",
    "regex_findall",
    "reject",
    "rejectattr",
    "replace",
    "reverse",
    "round",
    "safe",
    "select",
    "selectattr",
    "slice",
    "sort",
    "string",
    "striptags",
    "sum",
    "title",
    "trim",
    "truncate",
    "unique",
    "upper",
    "urlencode",
    "urlize",
    "wordcount",
    "xmlattr",
    "contains",
    # Common Ansible filters (subset, extend as needed)
    "b64decode",
    "b64encode",
    "basename",
    "dirname",
    "from_json",
    "to_json",
    "from_yaml",
    "to_yaml",
    "combine",
    "difference",
    "intersect",
    "flatten",
    "zip",
    "regex_search",
    "regex_replace",
    "bool",
    "type_debug",
    "json_query",
    "mandatory",
    "hash",
    "checksum",
    "lower",
    "upper",
    "capitalize",
    "unique",
    "dict2items",
    "items2dict",
    "password_hash",
    "path_join",
    "product",
    "quote",
    "split",
    "ternary",
    "to_nice_yaml",
    "tojson",
    "to_nice_json",
    "human_to_bytes",
    # Date/time-ish
    "strftime",
}


def _iter_files(*, exts: Tuple[str, ...]):
    yield from iter_project_files(
        extensions=exts,
        exclude_tests=EXCLUDE_TESTS,
        exclude_dirs=(".github",),
    )


def _is_filter_plugins_dir(path: str) -> bool:
    parts = os.path.normpath(path).split(os.sep)
    return "filter_plugins" in parts or ("plugins" in parts and "filter" in parts)


def _read(path: str) -> str:
    try:
        return read_text(path)
    except Exception:
        return ""


# ---------------------------
# Collect defined filters (AST)
# ---------------------------


class _FiltersCollector(ast.NodeVisitor):
    def __init__(self):
        self.defs: List[Tuple[str, str]] = []

    def visit_Return(self, node: ast.Return):
        self.defs.extend(self._extract_mapping(node.value))

    def _extract_mapping(self, node) -> List[Tuple[str, str]]:
        pairs: List[Tuple[str, str]] = []
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                key = (
                    k.value
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    else None
                )
                val = self._name_of(v)
                if key:
                    pairs.append((key, val))
            return pairs
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "dict"
        ):
            for kw in node.keywords or []:
                if kw.arg:
                    pairs.append((kw.arg, self._name_of(kw.value)))
            return pairs
        if isinstance(node, ast.Name):
            return []
        return []

    @staticmethod
    def _name_of(v) -> str:
        if isinstance(v, ast.Name):
            return v.id
        if isinstance(v, ast.Attribute):
            return v.attr
        return ""


def _collect_filters_from_filters_method(
    func: ast.FunctionDef,
) -> List[Tuple[str, str]]:
    c = _FiltersCollector()
    c.visit(func)

    name_dicts: Dict[str, List[Tuple[str, str]]] = {}
    returned_names: List[str] = []

    for n in ast.walk(func):
        if isinstance(n, ast.Assign):
            if len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                tgt = n.targets[0].id
                pairs = _FiltersCollector()._extract_mapping(n.value)
                if pairs:
                    name_dicts.setdefault(tgt, []).extend(pairs)
        elif isinstance(n, ast.Call):
            if isinstance(n.func, ast.Attribute) and n.func.attr == "update":
                obj = n.func.value
                if isinstance(obj, ast.Name) and n.args:
                    add_pairs = _FiltersCollector()._extract_mapping(n.args[0])
                    if add_pairs:
                        name_dicts.setdefault(obj.id, []).extend(add_pairs)
        elif isinstance(n, ast.Return) and isinstance(n.value, ast.Name):
            returned_names.append(n.value.id)

    for nm in returned_names:
        for p in name_dicts.get(nm, []):
            c.defs.append(p)

    # dedupe
    seen = set()
    out: List[Tuple[str, str]] = []
    for k, v in c.defs:
        if (k, v) not in seen:
            seen.add((k, v))
            out.append((k, v))
    return out


def collect_defined_filters() -> Set[str]:
    defined: Set[str] = set()
    for path in _iter_files(exts=(".py",)):
        if not _is_filter_plugins_dir(path):
            continue
        code = _read(path)
        if not code:
            continue
        try:
            tree = ast.parse(code, filename=path)
        except Exception:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "FilterModule":
                for item in node.body:
                    if isinstance(item, ast.FunctionDef) and item.name == "filters":
                        for fname, _call in _collect_filters_from_filters_method(item):
                            defined.add(fname)
    return defined


# ---------------------------
# Collect used filters (Jinja-only scanning with string stripping)
# ---------------------------

# Capture inner bodies of Jinja blocks
RE_JINJA_MUSTACHE = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
RE_JINJA_TAG = re.compile(r"\{%(.*?)%\}", re.DOTALL)

# Within a Jinja body, capture "| filter_name" (with args or not)
RE_PIPE_IN_BODY = re.compile(r"\|\s*([A-Za-z_]\w*)\b")

# Matches "{% filter filter_name %}"
RE_BLOCK_FILTER = re.compile(r"\{%\s*filter\s+([A-Za-z_]\w*)\b", re.DOTALL)


def _strip_quoted(text: str) -> str:
    """
    Remove content inside single/double quotes to avoid false positives for pipes in strings,
    e.g. lookup('pipe', "pacman ... | grep ... | awk ...") -> pipes are ignored.
    """
    out = []
    i = 0
    n = len(text)
    quote = None
    while i < n:
        ch = text[i]
        if quote is None:
            if ch in ("'", '"'):
                quote = ch
                i += 1
                continue
            out.append(ch)
            i += 1
        else:
            # inside quotes; handle simple escapes \" and \'
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
    return "".join(out)


def _extract_filters_from_jinja_body(body: str) -> Set[str]:
    # Strip quoted strings first so pipes inside strings are ignored
    body_no_str = _strip_quoted(body)
    return {m.group(1) for m in RE_PIPE_IN_BODY.finditer(body_no_str)}


def collect_used_filters() -> Set[str]:
    used: Set[str] = set()
    for path in _iter_files(exts=USAGE_EXTS):
        text = _read(path)
        if not text:
            continue

        # 1) Filters used in {{ ... }} blocks
        for m in RE_JINJA_MUSTACHE.finditer(text):
            used |= _extract_filters_from_jinja_body(m.group(1))

        # 2) Filters used in {% ... %} blocks (e.g., set, if, for)
        for m in RE_JINJA_TAG.finditer(text):
            used |= _extract_filters_from_jinja_body(m.group(1))

        # 3) Block filter form: {% filter name %} ... {% endfilter %}
        for m in RE_BLOCK_FILTER.finditer(text):
            used.add(m.group(1))

    return used


# ---------------------------
# Test
# ---------------------------


class TestAllUsedFiltersAreDefined(unittest.TestCase):
    def test_all_used_filters_have_definitions(self):
        defined = collect_defined_filters()
        used = collect_used_filters()

        # Remove built-ins and known-safe filters
        candidates = sorted(used - BUILTIN_FILTERS)

        # Unknown filters are those not defined locally
        unknown = [f for f in candidates if f not in defined]

        if unknown:
            lines = [
                "These filters are used in templates/YAML but have no local definition "
                "(and are not in BUILTIN_FILTERS):"
            ]
            for f in unknown:
                lines.append("- " + f)
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
