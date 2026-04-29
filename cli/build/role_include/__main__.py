#!/usr/bin/env python3

import os
import sys
import argparse
from collections import defaultdict, deque

from utils.cache.yaml import load_yaml

def find_roles(roles_dir, prefixes=None):
    """
    Find all roles in the given directory whose names start with
    any of the provided prefixes. If prefixes is empty or None,
    include all roles.
    """
    for entry in os.listdir(roles_dir):
        if prefixes:
            if not any(entry.startswith(pref) for pref in prefixes):
                continue
        path = os.path.join(roles_dir, entry)
        meta_file = os.path.join(path, 'meta', 'main.yml')
        if os.path.isdir(path) and os.path.isfile(meta_file):
            yield path, meta_file

def load_run_after(meta_file):
    """Return the role's `run_after` list (per req-010)."""
    from utils.roles.meta_lookup import get_role_run_after

    role_path = os.path.dirname(os.path.dirname(meta_file))
    role_name = os.path.basename(role_path)
    try:
        return get_role_run_after(role_path, role_name=role_name)
    except Exception:
        return []

def load_application_id(role_path):
    """Load the application_id from the vars/main.yml of the role."""
    vars_file = os.path.join(role_path, 'vars', 'main.yml')
    if os.path.exists(vars_file):
        data = load_yaml(vars_file)
        return data.get('application_id')
    return None

def build_dependency_graph(roles_dir, prefixes=None):
    """
    Build a dependency graph where each key is a role name and
    its value is a list of roles that depend on it.
    Also return in_degree counts and the roles metadata map.
    """
    graph = defaultdict(list)
    in_degree = defaultdict(int)
    roles = {}

    for role_path, meta_file in find_roles(roles_dir, prefixes):
        run_after = load_run_after(meta_file)
        application_id = load_application_id(role_path)
        role_name = os.path.basename(role_path)

        roles[role_name] = {
            'role_name': role_name,
            'run_after': run_after,
            'application_id': application_id,
            'path': role_path
        }

        for dependency in run_after:
            graph[dependency].append(role_name)
            in_degree[role_name] += 1

        if role_name not in in_degree:
            in_degree[role_name] = 0

    return graph, in_degree, roles

def find_cycle(roles):
    """
    Detect a cycle in the run_after relations:
      roles: dict mapping role_name -> { 'run_after': [...], ... }
    Returns a list of role_names forming the cycle (with the start repeated at end), or None.
    """
    visited = set()
    stack = set()

    def dfs(node, path):
        visited.add(node)
        stack.add(node)
        path.append(node)
        for dep in roles.get(node, {}).get('run_after', []):
            if dep not in visited:
                res = dfs(dep, path)
                if res:
                    return res
            elif dep in stack:
                idx = path.index(dep)
                return path[idx:] + [dep]
        stack.remove(node)
        path.pop()
        return None

    for role in roles:
        if role not in visited:
            cycle = dfs(role, [])
            if cycle:
                return cycle
    return None

def topological_sort(graph, in_degree, roles=None):
    """
    Perform topological sort on the dependency graph.
    If a cycle is detected, raise an Exception with detailed debug info.
    """

    queue = deque([r for r, d in in_degree.items() if d == 0])
    sorted_roles = []
    local_in = dict(in_degree)

    while queue:
        role = queue.popleft()
        sorted_roles.append(role)
        for nbr in graph.get(role, []):
            local_in[nbr] -= 1
            if local_in[nbr] == 0:
                queue.append(nbr)

    if len(sorted_roles) != len(in_degree):
        # Something went wrong: likely a cycle
        cycle = find_cycle(roles or {})
        unsorted = [r for r in in_degree if r not in sorted_roles]

        header = "❌ Dependency resolution failed"
        if cycle:
            reason = f"Circular dependency detected: {' -> '.join(cycle)}"
        else:
            reason = "Unresolved dependencies among roles (possible cycle or missing role)."

        details = []
        if unsorted:
            details.append("Unsorted roles and their declared run_after dependencies:")
            for r in unsorted:
                deps = roles.get(r, {}).get('run_after', [])
                details.append(f"  - {r} depends on {deps!r}")

        graph_repr = f"Full dependency graph: {dict(graph)!r}"

        raise Exception("\n".join([header, reason] + details + [graph_repr]))

    return sorted_roles

def print_dependency_tree(graph):
    """Print the dependency tree visually on the console."""
    def print_node(role, indent=0):
        print("  " * indent + role)
        for dep in graph.get(role, []):
            print_node(dep, indent + 1)

    all_roles = set(graph.keys())
    dependent = {r for deps in graph.values() for r in deps}
    roots = all_roles - dependent

    for root in roots:
        print_node(root)

def gen_condi_role_incl(roles_dir, prefixes=None):
    """
    Generate playbook entries based on the sorted order.
    Raises a ValueError if application_id is missing.
    """
    graph, in_degree, roles = build_dependency_graph(roles_dir, prefixes)
    sorted_names = topological_sort(graph, in_degree, roles)

    entries = []
    for role_name in sorted_names:
        role = roles[role_name]

        if role.get('application_id') is None:
            vars_file = os.path.join(role['path'], 'vars', 'main.yml')
            raise ValueError(f"'application_id' missing in {vars_file}")

        app_id = role['application_id']
        entries.append(
            f"- name: setup {app_id}\n"
            f"  when: ('{app_id}' | application_allowed(group_names, allowed_applications))\n"
            f"  include_role:\n"
            f"    name: {role_name}\n"
        )
        entries.append(
            f"- name: flush handlers after {app_id}\n"
            f"  meta: flush_handlers\n"
        )

    return entries

def main():
    parser = argparse.ArgumentParser(
        description='Generate an Ansible playbook include file from Docker roles, sorted by run_after order.'
    )
    parser.add_argument('roles_dir', help='Path to directory containing role folders')
    parser.add_argument(
        '-p', '--prefix',
        action='append',
        help='Only include roles whose names start with any of these prefixes; can be specified multiple times'
    )
    parser.add_argument('-o', '--output', default=None,
                        help='Output file path (default: stdout)')
    parser.add_argument('-t', '--tree', action='store_true',
                        help='Display the dependency tree of roles and exit')

    args = parser.parse_args()
    prefixes = args.prefix or []

    if args.tree:
        graph, _, _ = build_dependency_graph(args.roles_dir, prefixes)
        print_dependency_tree(graph)
        sys.exit(0)

    entries = gen_condi_role_incl(args.roles_dir, prefixes)
    output = ''.join(entries)

    if args.output:
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, 'w') as f:
            f.write(output)
        print(f"Playbook entries written to {args.output}")
    else:
        print(output)

if __name__ == '__main__':
    main()
