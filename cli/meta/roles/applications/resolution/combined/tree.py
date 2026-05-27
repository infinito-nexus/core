from __future__ import annotations

from .resolver import CombinedResolver
from .role_introspection import require_role_exists


def print_tree(start_role: str) -> None:
    """
    Print an ASCII tree showing [run_after] and [dependencies] for each role.

    Avoid infinite loops by:
      - marking already-expanded nodes
      - detecting cycles on the current stack
    """
    require_role_exists(start_role)

    resolver = CombinedResolver()

    expanded: set[str] = set()
    stack: list[str] = []

    def show_node(node: str, prefix: str, is_last: bool) -> None:
        connector = "└── " if is_last else "├── "
        if prefix == "":
            print(node)
        else:
            print(prefix + connector + node)

        if node in stack:
            print(prefix + ("    " if is_last else "│   ") + "↩︎ (cycle)")
            return

        if node in expanded:
            print(prefix + ("    " if is_last else "│   ") + "… (already shown)")
            return

        expanded.add(node)
        stack.append(node)

        edges = resolver.edges_for(node)

        groups: list[tuple[str, list[str]]] = []
        if edges.run_after:
            groups.append(("run_after", edges.run_after))
        if edges.dependencies:
            groups.append(("dependencies", edges.dependencies))
        if edges.services:
            groups.append(("services", edges.services))

        base_indent = prefix + ("    " if is_last else "│   ")

        for gi, (gname, children) in enumerate(groups):
            g_last = gi == (len(groups) - 1)
            g_connector = "└── " if g_last else "├── "
            print(base_indent + g_connector + f"[{gname}]")

            child_prefix = base_indent + ("    " if g_last else "│   ")
            for ci, child in enumerate(children):
                c_last = ci == (len(children) - 1)
                show_node(child, child_prefix, c_last)

        stack.pop()

    show_node(start_role, prefix="", is_last=True)
