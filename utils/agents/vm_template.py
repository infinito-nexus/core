"""The agent VM template: one versioned, credential-free disk image per VM
kind, built only from the template directory and its pinned package list.

The template directory holds ``packages.yml`` and a ``rootfs/`` tree copied
into the image. The runtime CLIs take their pinned version from the role that
installs them on a workstation, so a bump there reaches the template too.
"""

from __future__ import annotations

import shlex
import shutil
import stat
from pathlib import Path, PurePosixPath

from utils import PROJECT_ROOT
from utils.agents.workspace import VM_KINDS
from utils.cache.yaml import load_yaml
from utils.digests import SHA256
from utils.roles.mapping import ROLE_FILE_META_SERVICES

TEMPLATE_DIR = PROJECT_ROOT / "roles" / "svc-ai-agent-broker" / "files" / "vm-template"
SPEC_FILE = "packages.yml"
ROOTFS = "rootfs"
PROJECT = "project"
IMAGE_ID = "infinito-agent"
VERSION_FILE = "/etc/infinito/vm-template-version"
NPM_REGISTRY = "https://registry.npmjs.org"
DOWNLOAD_DIR = "/root/vm-template-downloads"
SPEC_KEYS = frozenset(
    {
        "version",
        "distribution",
        "release",
        "repositories",
        "snapshot",
        "apt",
        "runtimes",
        "tools",
        "probes",
    }
)


class VmTemplateError(ValueError):
    """A template build input breaks the build contract."""


def load_spec(template_dir: Path) -> dict:
    """Return the parsed ``packages.yml`` of ``template_dir``; refuse a key the
    build does not read, so no setting looks applied while it is ignored.

    Args:
        template_dir: the template directory.
    """
    spec = load_yaml(template_dir / SPEC_FILE) or {}
    unknown = sorted(set(spec) - SPEC_KEYS)
    if unknown:
        raise VmTemplateError(
            f"{template_dir / SPEC_FILE} holds keys the build does not read: "
            f"{', '.join(unknown)}"
        )
    return spec


def runtimes(template_dir: Path) -> frozenset[str]:
    """Return the agent runtimes the template ships.

    Args:
        template_dir: the template directory.
    """
    return frozenset((load_spec(template_dir).get("runtimes") or {}).keys())


def inputs(template_dir: Path) -> list[Path]:
    """Return every host path the build reads into the image, unresolved:
    ``packages.yml`` and every entry of the ``rootfs/`` tree.

    Args:
        template_dir: the template directory.
    """
    rootfs = template_dir / ROOTFS
    return [template_dir / SPEC_FILE, rootfs, *sorted(rootfs.rglob("*"))]


def _entry_problem(path: Path, root: Path) -> str:
    if root not in path.resolve().parents:
        return "outside the template"
    if path.is_symlink():
        return "a symlink"
    mode = path.lstat()
    if stat.S_ISDIR(mode.st_mode):
        return ""
    if not stat.S_ISREG(mode.st_mode):
        return "not a regular file"
    if mode.st_nlink > 1:
        return "a hard link"
    return ""


def assert_confined(paths: list[Path], template_dir: Path) -> None:
    """Refuse the build when any input resolves outside ``template_dir``, is a
    symlink, a hard link or not a regular file or directory.

    The check never opens a file, so a refused path is not read.

    Args:
        paths: the build inputs.
        template_dir: the only directory the build may read from.
    """
    root = template_dir.resolve()
    refused = [
        f"{path} ({problem})"
        for path in paths
        if (problem := _entry_problem(path, root))
    ]
    if refused:
        raise VmTemplateError(
            "the VM template build reads regular files only from "
            f"{template_dir}; refusing: {', '.join(refused)}"
        )


def assert_fresh(out_dir: Path) -> None:
    """Refuse an output directory that already holds anything, so no mkosi
    drop-in, extra tree or image the plan did not write takes part in the build.

    Args:
        out_dir: the build output directory.
    """
    if out_dir.exists() and (not out_dir.is_dir() or any(out_dir.iterdir())):
        raise VmTemplateError(
            f"the VM template build needs a new, empty --out directory; {out_dir} "
            "already holds files"
        )


def stage_rootfs(template_dir: Path, out_dir: Path) -> Path:
    """Copy the ``rootfs/`` tree into ``out_dir`` and return the copy mkosi
    builds from. The source is checked right before and right after the copy,
    so a link added after ``plan`` never reaches the image.

    Args:
        template_dir: the template directory.
        out_dir: the build output directory ``plan`` accepted.
    """
    assert_confined(inputs(template_dir), template_dir)
    staged = out_dir / ROOTFS
    shutil.copytree(template_dir / ROOTFS, staged, symlinks=True)
    assert_confined(inputs(template_dir), template_dir)
    return staged


def runtime_pins(spec: dict, roles_dir: Path) -> dict[str, tuple[str, str, str]]:
    """Return each runtime's npm package, pinned version and tarball sha256;
    package and version come from the role that pins them.

    Args:
        spec: the parsed ``packages.yml``.
        roles_dir: the repository ``roles/`` directory.
    """
    pins: dict[str, tuple[str, str, str]] = {}
    for name, entry in (spec.get("runtimes") or {}).items():
        role_dir = roles_dir / str(entry["role"])
        if role_dir.resolve().parent != roles_dir.resolve():
            raise VmTemplateError(
                f"runtime {name}: role {entry['role']!r} is not a role directory "
                f"directly under {roles_dir}"
            )
        services = load_yaml(role_dir / ROLE_FILE_META_SERVICES) or {}
        service = services[entry["entity"]]
        pins[name] = (
            service["update"]["package"],
            str(service["npm_version"]),
            str(entry["sha256"] or ""),
        )
    return pins


def _verified_download(url: str, sha256: str, target: str) -> list[str]:
    if not SHA256.fullmatch(sha256):
        raise VmTemplateError(
            f"{url} needs a sha256 of 64 lowercase hex digits in {SPEC_FILE}, "
            f"got {sha256!r}"
        )
    return [
        (
            "curl --retry 3 --connect-timeout 10 --max-time 300 -fsSL "
            f"{shlex.quote(url)} -o {shlex.quote(target)}"
        ),
        f"echo {shlex.quote(f'{sha256}  {target}')} | sha256sum --strict -c -",
    ]


def mkosi_files(spec: dict, pins: dict[str, tuple[str, str, str]]) -> dict[str, str]:
    """Return the mkosi project files the build renders, name to content.

    Args:
        spec: the parsed ``packages.yml``.
        pins: the runtime pins from ``runtime_pins``.
    """
    version = str(spec["version"])
    mirror = f"https://snapshot.debian.org/archive/debian/{spec['snapshot']}/"
    conf = "\n".join(
        [
            "[Distribution]",
            f"Distribution={spec['distribution']}",
            f"Release={spec['release']}",
            f"Repositories={','.join(spec['repositories'])}",
            f"Mirror={mirror}",
            "",
            "[Output]",
            "Format=disk",
            f"ImageId={IMAGE_ID}",
            f"ImageVersion={version}",
            f"Output={IMAGE_ID}-{version}",
            "",
            "[Content]",
            "Bootable=yes",
            "WithNetwork=yes",
            f"Packages={','.join(spec['apt'])}",
            "",
        ]
    )
    act = spec["tools"]["act"]
    act_tarball = f"{DOWNLOAD_DIR}/act.tgz"
    lines = ["#!/bin/sh", "set -eu", f"mkdir -p {DOWNLOAD_DIR}"]
    for package, pinned, sha256 in pins.values():
        tarball = f"{DOWNLOAD_DIR}/{package.split('/')[-1]}-{pinned}.tgz"
        url = f"{NPM_REGISTRY}/{package}/-/{package.split('/')[-1]}-{pinned}.tgz"
        lines += _verified_download(url, sha256, tarball)
        lines.append(f"npm install --global --ignore-scripts {shlex.quote(tarball)}")
    lines += _verified_download(
        act["url"].format(version=act["version"]),
        str(act["sha256"] or ""),
        act_tarball,
    )
    lines.append(
        f"tar -xzf {act_tarball} -C /usr/local/bin {shlex.quote(act['binary'])}"
    )
    lines.append(f"rm -rf {DOWNLOAD_DIR}")
    postinst = "\n".join([*lines, ""])
    finalize = "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            ': > "$BUILDROOT/etc/machine-id"',
            'rm -f "$BUILDROOT"/etc/ssh/ssh_host_*',
            f'mkdir -p "$BUILDROOT{PurePosixPath(VERSION_FILE).parent}"',
            f"printf '%s\\n' {shlex.quote(version)} > \"$BUILDROOT{VERSION_FILE}\"",
            "",
        ]
    )
    return {
        "mkosi.conf": conf,
        "mkosi.postinst.chroot": postinst,
        "mkosi.finalize": finalize,
    }


def plan(
    kind: str, template_dir: Path, roles_dir: Path, out_dir: Path
) -> list[list[str]]:
    """Return the commands that build the template of ``kind`` into
    ``out_dir``, after refusing a used output directory and every input that
    is not a regular file inside ``template_dir``.

    Args:
        kind: the VM kind, ``incus`` or ``proxmox``.
        template_dir: the template directory.
        roles_dir: the repository ``roles/`` directory.
        out_dir: the new, empty directory the build project and the image land in.
    """
    if kind not in VM_KINDS:
        raise VmTemplateError(f"kind '{kind}' is not one of {VM_KINDS}")
    assert_fresh(out_dir)
    assert_confined(inputs(template_dir), template_dir)
    spec = load_spec(template_dir)
    runtime_pins(spec, roles_dir)
    image = out_dir / f"{IMAGE_ID}-{spec['version']}"
    raw = f"{image}.raw"
    commands = [
        [
            "mkosi",
            f"--directory={out_dir / PROJECT}",
            f"--extra-tree={out_dir / ROOTFS}",
            f"--output-directory={out_dir}",
            "build",
        ],
        ["qemu-img", "convert", "-O", "qcow2", raw, f"{image}.qcow2"],
    ]
    if kind == "incus":
        commands.append(
            [
                "tar",
                "-cJf",
                f"{image}.metadata.tar.xz",
                "-C",
                str(out_dir / PROJECT),
                "metadata.yaml",
            ]
        )
    return commands


def incus_metadata(spec: dict) -> str:
    """Return the ``metadata.yaml`` an Incus VM image import needs.

    Args:
        spec: the parsed ``packages.yml``.
    """
    return "\n".join(
        [
            "architecture: x86_64",
            "creation_date: 0",
            "properties:",
            f"  description: {IMAGE_ID} {spec['version']}",
            f"  os: {spec['distribution']}",
            f"  release: {spec['release']}",
            f'  template_version: "{spec["version"]}"',
            "",
        ]
    )
