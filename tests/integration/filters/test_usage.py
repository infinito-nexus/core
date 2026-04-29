import ast
import os
import re
import unittest
from typing import Dict, List, Tuple, Optional

from utils.cache.files import iter_project_files, read_text

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))

SEARCH_EXTS = (".yml", ".yaml", ".j2", ".jinja2", ".tmpl", ".py")


def _iter_files(*, py_only: bool = False):
    exts = (".py",) if py_only else SEARCH_EXTS
    yield from iter_project_files(extensions=exts)


def _is_filter_plugins_dir(path: str) -> bool:
    parts = os.path.normpath(path).split(os.sep)
    return "filter_plugins" in parts or ("plugins" in parts and "filter" in parts)


def _read(path: str) -> str:
    try:
        return read_text(path)
    except Exception:
        return ""


# ---------------------------
# Filter definition extraction
# ---------------------------


class _FiltersCollector(ast.NodeVisitor):
    """
    Extract mappings returned by FilterModule.filters().
    Handles:
      return {'name': fn, "x": y}
      d = {'name': fn}; d.update({...}); return d
      return dict(name=fn, x=y)
    """

    def __init__(self):
        self.defs: List[Tuple[str, str]] = []  # (filter_name, callable_name)

    def visit_Return(self, node: ast.Return):
        mapping = self._extract_mapping(node.value)
        for k, v in mapping:
            self.defs.append((k, v))

    def _extract_mapping(self, node) -> List[Tuple[str, str]]:
        pairs: List[Tuple[str, str]] = []

        # dict literal
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

        # dict(...) call
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "dict"
        ):
            # keywords: dict(name=fn)
            for kw in node.keywords or []:
                if kw.arg:
                    pairs.append((kw.arg, self._name_of(kw.value)))
            return pairs

        # Name (variable) that might be a dict assembled earlier in the function
        if isinstance(node, ast.Name):
            # Fallback: we can't easily dataflow-resolve here; handled elsewhere by walking Assign/Call
            return []

        return []

    @staticmethod
    def _name_of(v) -> str:
        if isinstance(v, ast.Name):
            return v.id
        if isinstance(v, ast.Attribute):
            return v.attr  # take right-most name
        return ""


def _collect_filters_from_filters_method(
    func: ast.FunctionDef,
) -> List[Tuple[str, str]]:
    """
    Walks the function to assemble any mapping that flows into the return.
    We capture direct return dicts and also a common pattern:
        d = {...}
        d.update({...})
        return d
    """
    collector = _FiltersCollector()
    collector.visit(func)

    # additionally scan simple 'X = {...}' and 'X.update({...})' patterns,
    # and if 'return X' occurs, merge those dicts.
    name_dicts: Dict[str, List[Tuple[str, str]]] = {}
    returns: List[str] = []

    for n in ast.walk(func):
        if isinstance(n, ast.Assign):
            # X = { ... }
            if len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                tgt = n.targets[0].id
                pairs = _FiltersCollector()._extract_mapping(n.value)
                if pairs:
                    name_dicts.setdefault(tgt, []).extend(pairs)
        elif isinstance(n, ast.Call):
            # X.update({ ... })
            if isinstance(n.func, ast.Attribute) and n.func.attr == "update":
                obj = n.func.value
                if isinstance(obj, ast.Name):
                    add_pairs = _FiltersCollector()._extract_mapping(
                        n.args[0] if n.args else None
                    )
                    if add_pairs:
                        name_dicts.setdefault(obj.id, []).extend(add_pairs)
        elif isinstance(n, ast.Return) and isinstance(n.value, ast.Name):
            returns.append(n.value.id)

    for rname in returns:
        for p in name_dicts.get(rname, []):
            collector.defs.append(p)

    # dedupe
    seen = set()
    out: List[Tuple[str, str]] = []
    for k, v in collector.defs:
        if (k, v) not in seen:
            seen.add((k, v))
            out.append((k, v))
    return out


def _ast_collect_filters_from_file(path: str) -> List[Tuple[str, str, str]]:
    code = _read(path)
    if not code:
        return []
    try:
        tree = ast.parse(code, filename=path)
    except Exception:
        return []

    results: List[Tuple[str, str, str]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "FilterModule":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "filters":
                    for fname, callname in _collect_filters_from_filters_method(item):
                        results.append((fname, callname, path))
    return results


def collect_defined_filters() -> List[Dict[str, str]]:
    found: List[Dict[str, str]] = []
    for path in _iter_files(py_only=True):
        if not _is_filter_plugins_dir(path):
            continue
        for filter_name, callable_name, fpath in _ast_collect_filters_from_file(path):
            found.append(
                {"filter": filter_name, "callable": callable_name, "file": fpath}
            )
    return found


# ---------------------------
# Usage detection
# ---------------------------


def _scan_filter_usage(
    definitions: List[Dict[str, str]],
) -> Dict[str, Dict[str, bool]]:
    """Single-pass inverted scan: for every project file, check all filters at once.

    Complexity before (per-filter loop): O(N_filters * M_files * 4_regex). For this
    repo that is ~50 filters × ~5000 files × 4 patterns ≈ 1M regex calls.

    Complexity now (inverted): O(M_files * 2_master_regex) for Jinja, plus one
    combined regex per .py file for Python callables. ~10k regex calls total.

    The two master regexes use alternation over all filter names — ``bare_pat``
    matches ``| name`` anywhere (superset of the ``{{ … | name }}`` and
    ``{% … | name %}`` patterns the old code carried separately), while
    ``block_pat`` covers ``{% filter name %}``.

    Returns:
      ``{filter_name: {"used_any": bool, "used_outside": bool}}``
    """
    # Map filter name → its own definition file (skip self-matches).
    def_file_by_name: Dict[str, str] = {
        d["filter"]: os.path.realpath(d["file"]) for d in definitions
    }

    # Reverse index: callable name → filter name (for the Python-call match group).
    callable_to_filter: Dict[str, str] = {}
    for d in definitions:
        c = d.get("callable")
        if c:
            callable_to_filter[c] = d["filter"]

    # Build master alternations.
    escaped_names = [re.escape(d["filter"]) for d in definitions]
    name_alt = "(" + "|".join(escaped_names) + ")"
    bare_pat = re.compile(r"\|\s*" + name_alt + r"\b")
    block_pat = re.compile(r"\{%\s*filter\s+" + name_alt + r"\b")

    if callable_to_filter:
        escaped_callables = [re.escape(c) for c in callable_to_filter]
        call_alt = "(" + "|".join(escaped_callables) + ")"
        call_pat: Optional[re.Pattern] = re.compile(r"\b" + call_alt + r"\s*\(")
    else:
        call_pat = None

    state: Dict[str, Dict[str, bool]] = {
        d["filter"]: {"used_any": False, "used_outside": False} for d in definitions
    }

    for path in _iter_files(py_only=False):
        content = _read(path)
        if not content:
            continue

        path_real = os.path.realpath(path)
        is_test_path = "/tests/" in path or path.endswith("tests")

        def _record(name: str) -> None:
            # Skip self-matches — a filter's own definition file is not a usage site.
            if path_real == def_file_by_name.get(name):
                return
            s = state[name]
            s["used_any"] = True
            if not is_test_path:
                s["used_outside"] = True

        for m in bare_pat.finditer(content):
            _record(m.group(1))
        for m in block_pat.finditer(content):
            _record(m.group(1))

        if call_pat is not None and path.endswith(".py"):
            for m in call_pat.finditer(content):
                _record(callable_to_filter[m.group(1)])

    return state


class TestFilterDefinitionsAreUsed(unittest.TestCase):
    def test_every_defined_filter_is_used(self):
        definitions = collect_defined_filters()
        if not definitions:
            self.skipTest("No filters found under plugins/filter/.")

        state = _scan_filter_usage(definitions)

        unused = []
        for d in definitions:
            s = state[d["filter"]]
            if not s["used_any"]:
                unused.append(
                    (d["filter"], d["callable"], d["file"], "not used anywhere")
                )
            elif not s["used_outside"]:
                unused.append(
                    (d["filter"], d["callable"], d["file"], "only used in tests")
                )

        if unused:
            msg = ["The following filters are invalidly unused:"]
            for f, c, p, reason in sorted(unused):
                msg.append(
                    f"- '{f}' (callable '{c or 'unknown'}') defined in {p} → {reason}"
                )
            self.fail("\n".join(msg))


if __name__ == "__main__":
    unittest.main()
