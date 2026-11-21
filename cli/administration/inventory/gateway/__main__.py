from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cli.administration.inventory.mesh.__main__ import parse_pairs
from cli.administration.inventory.mesh.inventory import groups_of, host_applications

from .plan import APPLICATION_ID, SERVICE_KEY, plan_links
from .write import MODEL_KEY, HostVars, apply_links


def _models(
    links, host_vars: HostVars, given: dict[str, str]
) -> tuple[dict[str, str], list[str]]:
    models: dict[str, str] = {}
    missing: list[str] = []
    for link in links:
        held = (
            (host_applications(host_vars.host_vars_dir, link.consumer) or {})
            .get(APPLICATION_ID, {})
            .get("services", {})
            .get(SERVICE_KEY, {})
            .get(MODEL_KEY)
        )
        model = given.get(link.gateway) or (held if isinstance(held, str) else "")
        if model:
            models[link.consumer] = model
        else:
            missing.append(f"{link.consumer} (gateway {link.gateway})")
    return models, missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Point every host that names a gateway host at that host's LiteLLM "
            "gateway over the mesh, with one virtual key per consuming host."
        )
    )
    parser.add_argument(
        "--inventory",
        action="append",
        required=True,
        help="inventory file of the deploy; repeatable, pass every one of them",
    )
    parser.add_argument(
        "--host-vars-dir",
        required=True,
        help="directory holding one <host>.yml per host of those inventories",
    )
    parser.add_argument(
        "--vault-password-file",
        required=True,
        help="password file a key is encrypted with",
    )
    parser.add_argument(
        "--host-vault-password-file",
        action="append",
        default=[],
        metavar="HOST=FILE",
        help=(
            "password file of a host deployed with its own vault password; "
            "repeatable, a host left out uses --vault-password-file"
        ),
    )
    parser.add_argument(
        "--chat-model",
        action="append",
        default=[],
        metavar="GATEWAY=MODEL",
        help=(
            "the LITELLM_CHAT_MODEL of gateway host GATEWAY, which every consumer "
            "of its consuming hosts is configured with; repeatable, required "
            "until a consuming host holds one"
        ),
    )
    parser.add_argument(
        "--rotate",
        action="append",
        default=[],
        metavar="HOST",
        help="mint a new key for this consuming host only; repeatable",
    )
    args = parser.parse_args(argv)

    host_vars_dir = Path(args.host_vars_dir).resolve()
    if not host_vars_dir.is_dir():
        print(f"[FATAL] host_vars dir not found: {host_vars_dir}", file=sys.stderr)
        return 1
    groups = groups_of([Path(entry).resolve() for entry in args.inventory])
    hosts = sorted({host for members in groups.values() for host in members})
    if not hosts:
        print("[FATAL] no host resolved from the inventories", file=sys.stderr)
        return 1

    password_files = {
        host: Path(path).resolve()
        for host, path in parse_pairs(
            args.host_vault_password_file, "--host-vault-password-file", "FILE"
        ).items()
    }
    missing_files = sorted(
        str(path) for path in password_files.values() if not path.is_file()
    )
    if missing_files:
        print(
            f"[FATAL] vault password file(s) not found: {', '.join(missing_files)}",
            file=sys.stderr,
        )
        return 1

    try:
        links = plan_links(hosts, lambda host: host_applications(host_vars_dir, host))
    except (TypeError, ValueError) as error:
        print(f"[FATAL] {error}", file=sys.stderr)
        return 1

    unknown = sorted(set(args.rotate) - {link.consumer for link in links})
    if unknown:
        print(
            f"[FATAL] --rotate names no consuming host: {', '.join(unknown)}",
            file=sys.stderr,
        )
        return 1

    host_vars = HostVars(
        host_vars_dir, Path(args.vault_password_file).resolve(), password_files
    )
    models, without = _models(
        links, host_vars, parse_pairs(args.chat_model, "--chat-model", "MODEL")
    )
    if without:
        print(
            "[FATAL] no chat model for "
            + ", ".join(without)
            + ": pass --chat-model GATEWAY=<that gateway's LITELLM_CHAT_MODEL>",
            file=sys.stderr,
        )
        return 1

    revoked = apply_links(
        links, hosts, host_vars, models=models, rotate=set(args.rotate)
    )
    written = host_vars.flush()
    for link in links:
        print(f"[INFO] {link.consumer}: gateway {link.gateway} at {link.url}")
    for gateway, names in sorted(revoked.items()):
        print(f"[INFO] {gateway}: dropped the key of {', '.join(names)}")
    print(f"[INFO] {len(written)} host_vars written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
