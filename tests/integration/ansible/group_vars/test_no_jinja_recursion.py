import re
import unittest
from collections import defaultdict

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

# Directory containing group_vars/all/*.yml
GROUPVARS_DIR = PROJECT_ROOT / "group_vars" / "all"
JINJA_RE = re.compile(r"{{\s*([^}]+)\s*}}")
# Matches variables like foo.bar, foo["bar"], foo['bar']
VAR_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*(?:\.(?:[A-Za-z_][A-Za-z0-9_]*|\[\"[^\"]+\"\]))*"
)


def load_all_yaml():
    """
    Load and merge all YAML files under GROUPVARS_DIR, stripping 'defaults_' or 'default_' prefixes.
    """
    result = {}
    for yaml_path in GROUPVARS_DIR.glob("*.yml"):
        data = load_yaml_any(str(yaml_path)) or {}
        for k, v in data.items():
            base = k
            for p in ("defaults_", "default_"):
                base = base.removeprefix(p)
            if (
                base in result
                and isinstance(result[base], dict)
                and isinstance(v, dict)
            ):
                result[base].update(v)
            else:
                result[base] = v
    return result


def find_jinja_refs(val):
    """
    Find all unconditional Jinja variable paths inside {{…}} (including bracket-notation).
    Skip any expression containing ' if ' and ' else '.
    """
    refs = []
    if not isinstance(val, str):
        return refs
    for inner in JINJA_RE.findall(val):
        expr = inner.strip()
        if " if " in expr and " else " in expr:
            continue
        for m in VAR_PATTERN.finditer(expr):
            var = m.group(0)
            # normalize bracket notation foo["bar"] -> foo.bar
            var = re.sub(r"\[\"([^\"]+)\"\]", r".\1", var)
            var = re.sub(r"\['([^']+)'\]", r".\1", var)
            refs.append(var)
    return refs


def build_edges(vars_dict):
    """
    Walk the variables dict, return list of (source_key, referenced_var) edges.
    """
    edges = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, [*path, k])
        elif isinstance(node, list):
            for i, e in enumerate(node):
                walk(e, [*path, f"[{i}]"])
        else:
            full_key = ".".join(path)
            edges.extend((full_key, ref) for ref in find_jinja_refs(node))

    walk(vars_dict, [])
    return edges


class TestNoJinjaReferenceCycles(unittest.TestCase):
    def test_users_applications_cycle(self):
        all_vars = load_all_yaml()
        edges = build_edges(all_vars)

        user_to_app = any(
            src.startswith("users.") and ref == "applications" for src, ref in edges
        )
        app_to_user = any(
            src.startswith("applications.") and ref.startswith("users.")
            for src, ref in edges
        )
        if user_to_app and app_to_user:
            self.fail(
                "❌ Indirect Jinja-cycle detected:\n"
                "   a) a `users.*` key references `applications`\n"
                "   b) an `applications.*` key references `users.*`\n"
                "→ Combined this forms a cycle users → applications → users"
            )

    def test_no_unconditional_recursive_loops(self):
        all_vars = load_all_yaml()
        edges = build_edges(all_vars)
        graph = defaultdict(set)
        for src, ref in edges:
            graph[src].add(ref)

        def dfs(node, visited, stack):
            if node in stack:
                return [*stack[stack.index(node) :], node]
            if node in visited:
                return None
            visited.add(node)
            stack.append(node)
            for nxt in graph.get(node, []):
                cycle = dfs(nxt, visited, stack)
                if cycle:
                    return cycle
            stack.pop()
            return None

        for node in list(graph):
            cycle = dfs(node, set(), [])
            if cycle:
                self.fail(
                    "❌ Jinja recursion cycle detected:\n    " + " -> ".join(cycle)
                )


if __name__ == "__main__":
    unittest.main()
