#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path

# Ensure imports work when invoked as a script (subprocess without PYTHONPATH).
repo_root = Path(__file__).resolve().parents[3]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from utils.cache.applications import get_application_defaults  # noqa: E402
from utils.cache.files import read_text  # noqa: E402
from utils.cache.users import get_user_defaults  # noqa: E402
from utils.cache.yaml import load_yaml_str  # noqa: E402


def load_yaml_file(path):
    # Inline preprocessing: strip !vault entries (which would fail YAML
    # parsing) before handing the text to the cached string parser. The
    # cache's path-keyed loader is bypassed on purpose — this caller
    # mutates content per call, so each parse is intentionally fresh.
    try:
        content = read_text(str(path))
        content = re.sub(
            r"(?m)^([ \t]*[^\s:]+):\s*!vault[\s\S]+?(?=^\S|\Z)",
            r"\1: \"<vaulted>\"\n",
            content,
        )
        return load_yaml_str(content)
    except Exception as e:
        print(f"Warning: Could not parse {path}: {e}", file=sys.stderr)
        return None


def recursive_keys(d, prefix=""):
    keys = set()
    if isinstance(d, dict):
        for k, v in d.items():
            full = f"{prefix}.{k}" if prefix else k
            keys.add(full)
            keys.update(recursive_keys(v, full))
    return keys


def compare_application_keys(applications, application_defaults, source):
    errs = []
    for app_id, conf in applications.items():
        if app_id not in application_defaults:
            errs.append(f"{source}: Unknown application '{app_id}'")
            continue
        default = application_defaults[app_id]
        app_keys = recursive_keys(conf)
        def_keys = recursive_keys(default)
        for key in app_keys:
            if key.startswith("credentials"):
                continue
            if key not in def_keys:
                errs.append(f"{source}: Missing default for {app_id}: {key}")
    return errs


def compare_user_keys(users, user_defaults, source):
    errs = []
    for user, conf in users.items():
        if user not in user_defaults:
            print(
                f"Warning: {source}: Unknown user '{user}'",
                file=sys.stderr,
            )
            continue
        def_conf = user_defaults[user]
        for key in conf:
            if key in ("password", "credentials"):
                continue
            if key not in def_conf:
                errs.append(f"Missing default for user '{user}': key '{key}'")
    return errs


def load_inventory_files(inv_dir):
    all_data = {}
    p = Path(inv_dir)
    for f in p.glob("*.yml"):
        data = load_yaml_file(f)
        if isinstance(data, dict):
            apps = data.get("applications")
            if apps:
                all_data[str(f)] = apps
    for d in p.glob("*_vars"):
        if d.is_dir():
            for f in d.rglob("*.yml"):
                data = load_yaml_file(f)
                if isinstance(data, dict):
                    apps = data.get("applications")
                    if apps:
                        all_data[str(f)] = apps
    return all_data


def validate_host_keys(app_ids, inv_dir):
    errs = []
    p = Path(inv_dir)
    # Scan all top-level YAMLs for 'all.children'
    for f in p.glob("*.yml"):
        data = load_yaml_file(f)
        if not isinstance(data, dict):
            continue
        all_node = data.get("all", {})
        children = all_node.get("children")
        if not isinstance(children, dict):
            continue
        for grp in children.keys():
            if grp not in app_ids:
                errs.append(f"{f}: Invalid group '{grp}' (not in application_ids)")
    return errs


def main():
    p = argparse.ArgumentParser()
    p.add_argument("inventory_dir")
    p.add_argument(
        "--roles-dir",
        default=str(repo_root / "roles"),
        help="Path to the repository roles directory.",
    )
    args = p.parse_args()
    application_defaults = get_application_defaults(roles_dir=args.roles_dir)
    user_defaults = get_user_defaults(roles_dir=args.roles_dir)
    if not application_defaults:
        print(
            "Error: No application defaults discovered in roles directory",
            file=sys.stderr,
        )
        sys.exit(1)
    if not user_defaults:
        print("Error: No user defaults discovered in roles directory", file=sys.stderr)
        sys.exit(1)
    app_errs = []
    inv_files = load_inventory_files(args.inventory_dir)
    for src, apps in inv_files.items():
        app_errs.extend(compare_application_keys(apps, application_defaults, src))
    user_errs = []
    for fpath in Path(args.inventory_dir).rglob("*.yml"):
        data = load_yaml_file(fpath)
        if isinstance(data, dict) and "users" in data:
            errs = compare_user_keys(data["users"], user_defaults, str(fpath))
            for e in errs:
                print(e, file=sys.stderr)
            user_errs.extend(errs)
    host_errs = validate_host_keys(set(application_defaults), args.inventory_dir)
    app_errs.extend(host_errs)
    if app_errs or user_errs:
        if app_errs:
            print("Validation failed with the following issues:")
            for e in app_errs:
                print(f"- {e}")
        sys.exit(1)
    print("Inventory directory is valid against defaults and hosts.")
    sys.exit(0)


if __name__ == "__main__":
    main()
