from __future__ import annotations

import argparse
import sys

from cli import PROJECT_ROOT

from . import verify


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m cli.meta.roles.services.called",
        description=(
            "Verify required_by coverage in an Ansible run log. For every "
            "role declaring `required_by` in its meta/services.yml that "
            "matches the deployed apps' categories or role ids, assert that "
            "the role's body actually executed in the log."
        ),
    )
    p.add_argument(
        "--logfile",
        required=True,
        help="Path to the Ansible run log (read from the host filesystem).",
    )
    p.add_argument(
        "--apps",
        required=True,
        help="Comma-separated deployed role ids (e.g. `web-app-yourls,web-svc-css`).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    deployed = [a.strip() for a in args.apps.split(",") if a.strip()]

    ok, missing = verify(
        roles_dir=PROJECT_ROOT / "roles",
        log_path=args.logfile,
        deployed_role_ids=deployed,
    )
    if ok:
        print(f">>> system-services: OK for {args.apps}")
        return 0
    print(
        f"[ERROR] required role(s) did not execute for deploy '{args.apps}':",
        file=sys.stderr,
    )
    for role in missing:
        print(f"          - {role}", file=sys.stderr)
    print(
        "        Check `required_by` declarations in roles/*/meta/services.yml "
        "and the include chain that should have triggered the role.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
