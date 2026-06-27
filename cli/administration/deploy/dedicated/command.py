from __future__ import annotations

import argparse
import subprocess
from typing import Any

from .apps import validate_application_ids
from .modes import add_dynamic_mode_args, build_modes_from_args, load_modes_from_yaml
from .paths import INVENTORY_VALIDATOR_PATH, MODES_FILE, PLAYBOOK_PATH, PROJECT_ROOT
from .runner import run_ansible_playbook


def _get_ansible_playbook_help() -> str:
    """
    Best-effort retrieval of `ansible-playbook --help`.

    This is executed only when the user asks for --help, so runtime cost is negligible.
    """
    try:
        cp = subprocess.run(
            ["ansible-playbook", "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        out = (cp.stdout or "").rstrip()
    except FileNotFoundError:
        return "[ansible-playbook not found in PATH]"
    except Exception as exc:
        return f"[failed to run ansible-playbook --help: {exc}]"
    return out or "[ansible-playbook --help returned no output]"


def _passthrough_explanation() -> str:
    """
    Explain how native ansible-playbook flags are used with this wrapper.
    """
    return (
        "Passthrough of ansible-playbook options:\n"
        "  All unknown CLI options (e.g. --tags, --check, -e, --forks, ...)\n"
        "  are NOT parsed by this wrapper and are forwarded 1:1 to ansible-playbook.\n"
        "\n"
        "Important behavior:\n"
        "  - The wrapper injects its own -e variables first (MODE_*, APPLICATIONS_WHITELIST, ...).\n"
        "  - Your own ansible-playbook options come last and can therefore override them,\n"
        "    e.g. -e MODE_DEBUG=true.\n"
        "\n"
        "Examples:\n"
        "  Dry-run using Ansible check mode:\n"
        "    infinito administration deploy dedicated --check\n"
        "\n"
        "  Run only specific tags:\n"
        "    infinito administration deploy dedicated --tags nginx,certbot\n"
        "\n"
        "  Skip tags:\n"
        "    infinito administration deploy dedicated --skip-tags docker,build\n"
        "\n"
        "  Set or override extra variables:\n"
        "    infinito administration deploy dedicated -e MODE_DEBUG=true -e foo=bar\n"
        "\n"
        "  Increase parallelism (Ansible forks):\n"
        "    infinito administration deploy dedicated --forks 20\n"
        "\n"
        "  Start execution at a specific task:\n"
        '    infinito administration deploy dedicated --start-at-task "WEB | Deploy"\n'
    )


class _CombinedHelpAction(argparse.Action):
    """
    Replace default argparse help with:
      - wrapper help
      - ansible-playbook --help
      - passthrough usage explanation
    """

    def __call__(self, parser, namespace, values, option_string=None):  # type: ignore[override]
        wrapper_help = parser.format_help().rstrip()
        ansible_help = _get_ansible_playbook_help()
        extra = _passthrough_explanation().rstrip()

        print(wrapper_help)
        print("\n" + "=" * 80)
        print("ansible-playbook --help")
        print("=" * 80)
        print(ansible_help)
        print("\n" + "=" * 80)
        print("How to use ansible-playbook options with this wrapper")
        print("=" * 80)
        print(extra)

        raise SystemExit(0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deploy the Infinito.Nexus stack using ansible-playbook.",
        add_help=False,
    )

    # Custom combined help (-h / --help)
    parser.add_argument(
        "-h",
        "--help",
        action=_CombinedHelpAction,
        nargs=0,
        help="Show this help message and ansible-playbook --help.",
    )

    # Standard arguments
    parser.add_argument("inventory", help="Path to the inventory file.")
    parser.add_argument(
        "-l", "--limit", help="Limit execution to certain hosts or groups."
    )
    parser.add_argument(
        "-p", "--password-file", help="Vault password file for encrypted variables."
    )
    parser.add_argument(
        "-B", "--skip-build", action="store_true", help="Skip build phase."
    )
    parser.add_argument(
        "--id",
        nargs="+",
        default=[],
        dest="id",
        help="List of application_ids for partial deployment.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase verbosity (e.g. -vvv).",
    )
    parser.add_argument("--diff", action="store_true", help="Enable Ansible diff mode.")

    return parser


def _split_args(
    argv: list[str] | None,
    parser: argparse.ArgumentParser,
) -> tuple[argparse.Namespace, list[str]]:
    """
    Parse wrapper args and keep unknown args for direct ansible-playbook passthrough.

    This enables users to pass native Ansible flags like:
      --tags, --skip-tags, --check, --start-at-task, --forks, -e, ...
    """
    args, unknown = parser.parse_known_args(argv)
    return args, unknown


def _normalize_app_ids(raw_ids: list[str]) -> list[str]:
    """
    Normalize application IDs:
      - allow space-separated
      - allow comma-separated
      - allow mixed
    """
    result: list[str] = []

    for item in raw_ids:
        parts = [p.strip() for p in item.split(",") if p.strip()]
        result.extend(parts)

    # remove duplicates while preserving order
    seen = set()
    unique: list[str] = []
    for app in result:
        if app not in seen:
            seen.add(app)
            unique.append(app)

    return unique


def parse_args(
    argv: list[str] | None = None,
) -> tuple[Any, list[str], dict[str, Any]]:
    """Parse argv into ``(args, passthrough, modes_spec)``."""
    parser = build_parser()
    modes_meta = load_modes_from_yaml(MODES_FILE)
    modes_spec = add_dynamic_mode_args(parser, modes_meta)
    args, passthrough = _split_args(argv, parser)
    args.id = _normalize_app_ids(args.id)
    return args, passthrough, modes_spec


def run_from_args(
    args: Any,
    passthrough: list[str],
    modes_spec: dict[str, Any],
) -> int:
    """Validate, build the mode map, and dispatch to the playbook runner."""
    validate_application_ids(args.inventory, args.id)

    modes: dict[str, Any] = build_modes_from_args(modes_spec, args)

    run_ansible_playbook(
        repo_root=str(PROJECT_ROOT),
        playbook_path=PLAYBOOK_PATH,
        inventory_validator_path=INVENTORY_VALIDATOR_PATH,
        inventory=args.inventory,
        modes=modes,
        limit=args.limit,
        allowed_applications=args.id,
        password_file=args.password_file,
        verbose=args.verbose,
        skip_build=args.skip_build,
        diff=args.diff,
        ansible_args=passthrough,
    )

    return 0


def main(argv: list[str] | None = None) -> int:
    """Strict, explicit-only deploy entrypoint.

    Deploys exactly the application_ids passed via ``--id``; no
    swarm-infra auto-include. For dependency-driven swarm deploys use
    ``cli.administration.deploy.swarm``.
    """
    args, passthrough, modes_spec = parse_args(argv)
    return run_from_args(args, passthrough, modes_spec)
