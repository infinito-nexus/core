from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

from .credentials_generator import generate_credentials_for_roles
from .email_policy import apply_email_policy, carry_email_policy, inventory_is_new
from .filters import filter_dynamic_inventory, parse_roles_list
from .host_vars import (
    apply_vars_overrides,
    apply_vars_overrides_from_file,
    ensure_become_password,
    ensure_host_vars_file,
)
from .inventory_generator import generate_dynamic_inventory
from .mirror_overrides import apply_mirror_overrides
from .network_mode import apply_network_mode_from_env
from .passwords import generate_random_password
from .project import build_env_with_project_root, detect_project_root
from .remote_gateway import drop_gateway_role, named_gateway_host
from .services.disabler import (
    apply_services_disabled_from_env,
    reconcile_services_disabled_from_env,
)
from .tor_node import apply_tor_node_onion
from .users_generator import generate_user_passwords
from .yaml_io import dump_yaml, load_yaml


def _fatal(msg: str) -> None:
    raise SystemExit(f"[FATAL] {msg}")


def _read_become_password(stream) -> str:
    """The become password: prompted on a terminal, else the first line of *stream*.

    Args:
        stream: the text stream the operator piped the password into.
    """
    if stream.isatty():
        secret = getpass.getpass("Become password: ")
    else:
        line = stream.readline()
        secret = line[:-2] if line.endswith("\r\n") else line.removesuffix("\n")
    if not secret:
        _fatal("--become-password-stdin read no password from stdin")
    return secret


def _resolve_inventory_file(
    inventory_dir: Path, inventory_file_arg: str | None
) -> Path:
    if inventory_file_arg:
        return Path(inventory_file_arg).resolve()
    return (inventory_dir / "devices.yml").resolve()


def _resolve_mirrors_file(project_root: Path, mirror_arg: str | None) -> Path | None:
    """
    --mirror can be used in two ways:
      - --mirror            -> uses <repo-root>/mirrors.yml
      - --mirror /path/file -> uses the given path

    If mirror_arg is None, mirroring is disabled.
    """
    if mirror_arg is None:
        return None

    candidate = Path(mirror_arg)
    if not candidate.is_absolute():
        candidate = (project_root / candidate).resolve()

    return candidate.resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create or update a full inventory for a host and generate credentials "
            "for all selected applications."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "inventory_dir", help="Inventory directory (e.g. inventories/galaxyserver)."
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="Hostname to use in the inventory (default: localhost).",
    )
    parser.add_argument(
        "--become-password-stdin",
        action="store_true",
        help=(
            "Read the become password (vaulted) as the first line of stdin "
            "instead of keeping or generating one."
        ),
    )
    parser.add_argument(
        "--vars",
        required=False,
        help=(
            "Optional JSON object string with additional values for host_vars/<host>.yml. "
            "Merged and overwrites existing values."
        ),
    )
    parser.add_argument(
        "--inventory-file",
        default=None,
        help="Inventory YAML file path (default: <inventory-dir>/devices.yml).",
    )

    parser.add_argument(
        "--roles",
        nargs="+",
        help="Legacy include list (used only if neither --include nor --exclude is set).",
    )
    parser.add_argument(
        "--include",
        nargs="+",
        help="Only include these application_ids (mutually exclusive with --exclude).",
    )
    parser.add_argument(
        "--exclude",
        nargs="+",
        help="Exclude these application_ids (mutually exclusive with --include).",
    )

    parser.add_argument(
        "--vault-password-file",
        default=None,
        help="Vault password file path. Default: <inventory-dir>/.password",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=os.cpu_count() or 4,
        help="Worker threads for credentials generation (default: host CPU count, fallback 4).",
    )
    parser.add_argument(
        "--vars-file",
        default=None,
        help=(
            "Optional YAML file with additional values for host_vars/<host>.yml. "
            "Merged and overwrites existing values."
        ),
    )

    parser.add_argument(
        "--mirror",
        nargs="?",
        const="mirrors.yml",
        default=None,
        help=(
            "Apply docker image mirror overrides to host_vars "
            "applications.*.services.* (image/version). "
            "If used without value, defaults to <repo-root>/mirrors.yml. "
            "If a value is provided, it is treated as a path to the mirrors YAML/JSON file."
        ),
    )
    parser.add_argument(
        "--app-variants",
        default=None,
        help=(
            "JSON object {app_id: variant_index} mapping the matrix variant "
            "active in this round for each app. Forwarded to credential "
            "generation so shared-provider discovery (services.<k>.enabled+shared) "
            "respects the variant overlay. Apps not listed default to 0."
        ),
    )
    parser.add_argument(
        "--previous-host-vars",
        default=None,
        help=(
            "host_vars file of the inventory this run rebuilds from scratch. Its "
            "web-app-keycloak email policy and switch carry over, and the "
            "inventory counts as existing, so no mailbox policy is recorded "
            "against a realm that holds another one."
        ),
    )

    raw_args = sys.argv[1:] if argv is None else argv
    if any(arg.startswith("--become-password-stdin=") for arg in raw_args):
        _fatal("--become-password-stdin takes no value: pipe the password on stdin")
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        _fatal(
            f"{len(unknown)} unrecognized argument(s), not echoed; the become "
            "password goes on stdin with --become-password-stdin"
        )
    become_password = (
        _read_become_password(sys.stdin) if args.become_password_stdin else None
    )

    include_filter = parse_roles_list(args.include)
    exclude_filter = parse_roles_list(args.exclude)
    legacy_roles_filter = parse_roles_list(args.roles)

    if include_filter and exclude_filter:
        _fatal(
            "Options --include and --exclude are mutually exclusive. Use only one of them."
        )

    project_root = detect_project_root(Path(__file__).resolve())
    env = build_env_with_project_root(project_root)

    roles_dir = (project_root / "roles").resolve()
    mirrors_file = _resolve_mirrors_file(project_root, args.mirror)

    inventory_dir = Path(args.inventory_dir).resolve()
    inventory_dir.mkdir(parents=True, exist_ok=True)

    inventory_file = _resolve_inventory_file(inventory_dir, args.inventory_file)
    host_vars_file = (inventory_dir / "host_vars" / f"{args.host}.yml").resolve()

    if args.vault_password_file:
        vault_password_file = Path(args.vault_password_file).resolve()
    else:
        vault_password_file = (inventory_dir / ".password").resolve()
        if not vault_password_file.exists():
            print(
                f"[INFO] No --vault-password-file provided. Creating {vault_password_file} ..."
            )
            vault_password_file.parent.mkdir(parents=True, exist_ok=True)
            password = generate_random_password()
            fd = os.open(
                str(vault_password_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600
            )
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(password + "\n")
            try:
                vault_password_file.chmod(0o600)
            except PermissionError:
                print(
                    f"[WARN] Could not set permissions to 0o600 on {vault_password_file}.",
                    file=sys.stderr,
                )
        else:
            print(f"[INFO] Using existing vault password file: {vault_password_file}")

    tmp_inventory = (inventory_dir / "_inventory_full_tmp.yml").resolve()

    print(
        "[INFO] Generating dynamic inventory via python -m cli.administration.inventory.devices ..."
    )
    dyn_inv = generate_dynamic_inventory(
        host=args.host,
        tmp_inventory=tmp_inventory,
        env=env,
    )

    dyn_inv = filter_dynamic_inventory(
        dyn_inv,
        include_filter=include_filter,
        exclude_filter=exclude_filter,
        legacy_roles_filter=legacy_roles_filter,
    )

    gateway_host = named_gateway_host(
        host_vars_file,
        args.vars,
        Path(args.vars_file).resolve() if args.vars_file else None,
    )
    if gateway_host and drop_gateway_role(dyn_inv):
        print(
            f"[INFO] {args.host} uses the gateway on {gateway_host}: "
            "svc-ai-litellm is not provisioned here"
        )

    dyn_children = (dyn_inv.get("all", {}) or {}).get("children", {}) or {}
    application_ids = sorted(dyn_children.keys())

    new_inventory = not inventory_file.exists()
    fresh_inventory = inventory_is_new(
        inventory_file=inventory_file, host_vars_dir=host_vars_file.parent
    )
    if not new_inventory:
        print(f"[INFO] Merging into existing inventory: {inventory_file}")
        base_inv = load_yaml(inventory_file)
    else:
        print(f"[INFO] Creating new inventory file: {inventory_file}")
        base_inv = {}

    merged_inv = _merge_inventories(base_inv, dyn_inv, host=args.host)
    if gateway_host and drop_gateway_role(merged_inv):
        print(f"[INFO] Removed svc-ai-litellm from {inventory_file}")
    dump_yaml(inventory_file, merged_inv)

    print(f"[INFO] Ensuring host_vars for host '{args.host}' at {host_vars_file}")
    ensure_host_vars_file(
        host_vars_file=host_vars_file,
        host=args.host,
    )
    reconcile_services_disabled_from_env(
        host_vars_file=host_vars_file, roles_dir=roles_dir
    )

    if args.previous_host_vars and carry_email_policy(
        previous_host_vars_file=Path(args.previous_host_vars).resolve(),
        host_vars_file=host_vars_file,
    ):
        print("[INFO] Carried the realm email policy over from the replaced inventory")

    print(f"[INFO] Ensuring ansible_become_password for host '{args.host}'")
    ensure_become_password(
        host_vars_file=host_vars_file,
        vault_password_file=vault_password_file,
        become_password=become_password,
    )

    print(
        f"[INFO] Pinning a password for every user the {len(application_ids)} "
        "resolved applications declare and every catalogue user holding an account..."
    )
    pinned = generate_user_passwords(
        roles_dir=roles_dir,
        application_ids=application_ids,
        host_vars_file=host_vars_file,
        vault_password_file=vault_password_file,
    )
    print(f"[INFO] Pinned {pinned} user password(s)")

    app_variants: dict[str, int] = {}
    if args.app_variants:
        try:
            parsed = json.loads(args.app_variants)
        except Exception as exc:
            _fatal(f"--app-variants must be valid JSON: {exc}")
        if not isinstance(parsed, dict):
            _fatal("--app-variants must be a JSON object")
        for app_id, raw_index in parsed.items():
            try:
                app_variants[str(app_id)] = int(raw_index)
            except (TypeError, ValueError) as exc:
                _fatal(
                    f"--app-variants[{app_id!r}] must be an integer, got {raw_index!r}: {exc}"
                )

    if application_ids:
        print(
            f"[INFO] Generating credentials for {len(application_ids)} applications..."
        )
        generate_credentials_for_roles(
            application_ids=application_ids,
            roles_dir=roles_dir,
            host_vars_file=host_vars_file,
            vault_password_file=vault_password_file,
            project_root=project_root,
            env=env,
            workers=args.workers,
            app_variants=app_variants,
        )
    else:
        print(
            "[WARN] No application_ids found after filtering. Skipping credentials generation."
        )

    if args.vars_file:
        print(
            f"[INFO] Applying YAML overrides to host_vars for host '{args.host}' via --vars-file"
        )
        apply_vars_overrides_from_file(
            host_vars_file=host_vars_file, vars_file=Path(args.vars_file).resolve()
        )

    if args.vars:
        print(
            f"[INFO] Applying JSON overrides to host_vars for host '{args.host}' via --vars"
        )
        apply_vars_overrides(host_vars_file=host_vars_file, json_str=args.vars)

    if mirrors_file is not None:
        print(f"[INFO] Applying mirror overrides from: {mirrors_file}")
        apply_mirror_overrides(host_vars_file=host_vars_file, mirrors_file=mirrors_file)

    apply_tor_node_onion(
        host_vars_file=host_vars_file,
        application_ids=application_ids,
        base_dir=project_root,
    )

    apply_network_mode_from_env(host_vars_file)

    if apply_email_policy(
        host_vars_file=host_vars_file,
        application_ids=application_ids,
        host=args.host,
        roles_dir=roles_dir,
        new_inventory=fresh_inventory and not args.previous_host_vars,
        keycloak_variant=app_variants.get("web-app-keycloak"),
    ):
        print("[INFO] New inventory with mail provider: realm email policy mailbox")

    apply_services_disabled_from_env(
        host_vars_file=host_vars_file,
        inventory_file=inventory_file,
        roles_dir=roles_dir,
    )

    print(
        "[INFO] Done. Inventory and host_vars updated without deleting existing values."
    )
    return 0


def _merge_inventories(
    base: dict[str, Any], new: dict[str, Any], host: str
) -> dict[str, Any]:
    """
    Merge `new` inventory into `base` inventory without deleting existing groups/hosts/vars.

    For each group in `new`:
      - ensure the group exists in `base`
      - ensure `hosts` exists
      - ensure the given `host` is present in that group's `hosts`
    """
    base_all = base.setdefault("all", {})
    base_children = base_all.setdefault("children", {})

    new_all = new.get("all", {})
    new_children = (
        (new_all.get("children", {}) or {}) if isinstance(new_all, dict) else {}
    )

    for group_name, group_data in new_children.items():
        base_group = base_children.setdefault(group_name, {})
        base_hosts = base_group.setdefault("hosts", {})

        new_hosts = (group_data or {}).get("hosts", {}) or {}
        host_vars: dict[str, Any] = {}
        if isinstance(new_hosts, dict) and host in new_hosts:
            hv = new_hosts.get(host) or {}
            if isinstance(hv, dict):
                host_vars = hv

        if host not in base_hosts:
            base_hosts[host] = host_vars or {}

    return base
