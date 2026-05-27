#!/usr/bin/env python3
import os
import argparse
import json
from typing import Dict, Any, Optional, Iterable, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed

from cli.build.graph import build_mappings, output_graph

from . import PROJECT_ROOT


def find_roles(roles_dir: str) -> Iterable[Tuple[str, str]]:
    """
    Yield (role_name, role_path) for all roles in the given roles_dir.
    """
    for entry in os.listdir(roles_dir):
        path = os.path.join(roles_dir, entry)
        if os.path.isdir(path):
            yield entry, path


def process_role(
    role_name: str,
    roles_dir: str,
    depth: int,
    shadow_folder: Optional[str],
    output: str,
    preview: bool,
    verbose: bool,
    no_include_role: bool,   # currently unused, kept for CLI compatibility
    no_import_role: bool,    # currently unused, kept for CLI compatibility
    no_dependencies: bool,   # currently unused, kept for CLI compatibility
    no_run_after: bool,      # currently unused, kept for CLI compatibility
) -> None:
    """
    Worker function: build graphs and (optionally) write meta/tree.json for a single role.

    Note:
        This version no longer adds a custom top-level "dependencies" bucket.
        Only the graphs returned by build_mappings() are written.
    """
    role_path = os.path.join(roles_dir, role_name)

    if verbose:
        print(f"[worker] Processing role: {role_name}")

    # Build the full graph structure (all dep types / directions) for this role
    graphs: Dict[str, Any] = build_mappings(
        start_role=role_name,
        roles_dir=roles_dir,
        max_depth=depth,
    )

    # Preview mode: dump graphs to console instead of writing tree.json
    if preview:
        for key, data in graphs.items():
            if verbose:
                print(f"[worker] Previewing graph '{key}' for role '{role_name}'")
            # In preview mode we always output as console
            output_graph(data, "console", role_name, key)
        return

    # Non-preview: write meta/tree.json for this role
    if shadow_folder:
        tree_file = os.path.join(shadow_folder, role_name, "meta", "tree.json")
    else:
        tree_file = os.path.join(role_path, "meta", "tree.json")

    os.makedirs(os.path.dirname(tree_file), exist_ok=True)
    with open(tree_file, "w", encoding="utf-8") as f:
        json.dump(graphs, f, indent=2)

    print(f"Wrote {tree_file}")


def main():
    default_roles_dir = str(PROJECT_ROOT / "roles")

    parser = argparse.ArgumentParser(
        description="Generate all graphs for each role and write meta/tree.json"
    )
    parser.add_argument(
        "-d",
        "--role_dir",
        default=default_roles_dir,
        help=f"Path to roles directory (default: {default_roles_dir})",
    )
    parser.add_argument(
        "-D",
        "--depth",
        type=int,
        default=0,
        help="Max recursion depth (>0) or <=0 to stop on cycle",
    )
    parser.add_argument(
        "-o",
        "--output",
        choices=["yaml", "json", "console"],
        default="json",
        help="Output format for preview mode",
    )
    parser.add_argument(
        "-p",
        "--preview",
        action="store_true",
        help="Preview graphs to console instead of writing files",
    )
    parser.add_argument(
        "-s",
        "--shadow-folder",
        type=str,
        default=None,
        help="If set, writes tree.json to this shadow folder instead of the role's actual meta/ folder",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    # Toggles (kept for CLI compatibility, currently only meaningful for future extensions)
    parser.add_argument(
        "--no-include-role",
        action="store_true",
        help="Reserved: do not include include_role in custom dependency bucket",
    )
    parser.add_argument(
        "--no-import-role",
        action="store_true",
        help="Reserved: do not include import_role in custom dependency bucket",
    )
    parser.add_argument(
        "--no-dependencies",
        action="store_true",
        help="Reserved: do not include meta dependencies in custom dependency bucket",
    )
    parser.add_argument(
        "--no-run-after",
        action="store_true",
        help="Reserved: do not include run_after in custom dependency bucket",
    )

    args = parser.parse_args()

    if args.verbose:
        print(f"Roles directory: {args.role_dir}")
        print(f"Max depth: {args.depth}")
        print(f"Output format: {args.output}")
        print(f"Preview mode: {args.preview}")
        print(f"Shadow folder: {args.shadow_folder}")

    roles = [role_name for role_name, _ in find_roles(args.role_dir)]

    # For preview, run sequentially to avoid completely interleaved output.
    if args.preview:
        for role_name in roles:
            process_role(
                role_name=role_name,
                roles_dir=args.role_dir,
                depth=args.depth,
                shadow_folder=args.shadow_folder,
                output=args.output,
                preview=True,
                verbose=args.verbose,
                no_include_role=args.no_include_role,
                no_import_role=args.no_import_role,
                no_dependencies=args.no_dependencies,
                no_run_after=args.no_run_after,
            )
        return

    # Non-preview: roles are processed in parallel
    with ProcessPoolExecutor() as executor:
        futures = {
            executor.submit(
                process_role,
                role_name,
                args.role_dir,
                args.depth,
                args.shadow_folder,
                args.output,
                False,  # preview=False in parallel mode
                args.verbose,
                args.no_include_role,
                args.no_import_role,
                args.no_dependencies,
                args.no_run_after,
            ): role_name
            for role_name in roles
        }

        for future in as_completed(futures):
            role_name = futures[future]
            try:
                future.result()
            except Exception as exc:
                # Do not crash the whole run; report the failing role instead.
                print(f"[ERROR] Role '{role_name}' failed: {exc}")


if __name__ == "__main__":
    main()
