"""Build the agent VM template of one VM kind.

Usage: ``python -m cli.agents.vm_template --kind incus|proxmox --out <dir> [--dry-run]``.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from utils import PROJECT_ROOT
from utils.agents import vm_template
from utils.agents.workspace import VM_KINDS


def render_project(out_dir: Path) -> None:
    """Write the generated mkosi project and the Incus metadata under
    ``out_dir/project`` and stage the checked rootfs copy mkosi builds from.

    Args:
        out_dir: the build output directory.
    """
    vm_template.assert_fresh(out_dir)
    vm_template.assert_confined(
        vm_template.inputs(vm_template.TEMPLATE_DIR), vm_template.TEMPLATE_DIR
    )
    spec = vm_template.load_spec(vm_template.TEMPLATE_DIR)
    pins = vm_template.runtime_pins(spec, PROJECT_ROOT / "roles")
    files = vm_template.mkosi_files(spec, pins)
    project = out_dir / vm_template.PROJECT
    project.mkdir(parents=True)
    vm_template.stage_rootfs(vm_template.TEMPLATE_DIR, out_dir)
    for name, content in files.items():
        target = project / name
        target.write_text(content, encoding="utf-8")
        if name != "mkosi.conf":
            target.chmod(0o755)
    (project / "metadata.yaml").write_text(
        vm_template.incus_metadata(spec), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    """Run the build, or print its commands with ``--dry-run``.

    Args:
        argv: the command line without the program name.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=VM_KINDS)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        commands = vm_template.plan(
            args.kind, vm_template.TEMPLATE_DIR, PROJECT_ROOT / "roles", args.out
        )
        if args.dry_run:
            print("\n".join(" ".join(command) for command in commands))
            return 0
        render_project(args.out)
    except vm_template.VmTemplateError as exc:
        print(f"agents-vm-template: {exc}", file=sys.stderr)
        return 2
    for command in commands:
        subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
