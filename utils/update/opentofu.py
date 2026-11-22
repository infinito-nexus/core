from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import re
import subprocess
import tarfile
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update import fetch
from utils.update.base import is_maintained

REGISTRY = "https://registry.opentofu.org/v1/providers/{source}/versions"
VERSIONS_FILE = "versions.tf.json"
LOCK_FILE = ".terraform.lock.hcl"
BUILD = Path("files/shell/opentofu/build.sh")
RELEASE = re.compile(r"^\d+\.\d+\.\d+$")
GENERAL_VARS = PROJECT_ROOT / "group_vars" / "all" / "00_general.yml"
ARCHITECTURE_BY_KERNEL = "HOST_ARCHITECTURE_BY_KERNEL"

Fetch = Callable[[str], bytes]


@dataclass(frozen=True)
class ProviderPin:
    """Args:
    path: the ``versions.tf.json`` that pins the provider.
    role: the role that ships it.
    source: the provider's registry address, ``<namespace>/<type>``.
    version: the exact version it pins.
    """

    path: Path
    role: str
    source: str
    version: str


@dataclass(frozen=True)
class ProviderPinUpdate:
    """Args:
    pin: the pin to move.
    latest: the newest release of its provider.
    """

    pin: ProviderPin
    latest: str


def _release_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def collect_pins(repo_root: Path) -> list[ProviderPin]:
    """Args:
        repo_root: repository root holding ``roles/``.

    Returns:
        Every exact provider pin of a maintained role's OpenTofu files.
    """
    roles_root = repo_root / "roles"
    pins = []
    for path in sorted(roles_root.glob(f"*/files/opentofu/**/{VERSIONS_FILE}")):
        role = path.relative_to(roles_root).parts[0]
        if not is_maintained(roles_root, role):
            continue
        text = path.read_text(encoding="utf-8")  # nocheck: cache-read rewritten
        declared = json.loads(text)["terraform"]["required_providers"]
        pins.extend(
            ProviderPin(path, role, entry["source"], entry["version"])
            for entry in declared.values()
            if RELEASE.match(str(entry.get("version", "")))
        )
    return pins


def latest_release(source: str, get: Fetch = fetch.get) -> str | None:
    """Args:
        source: the provider's registry address.
        get: reads an https URL.

    Returns:
        The newest version of the provider that is no pre-release.
    """
    answer = json.loads(get(REGISTRY.format(source=source)))
    releases = [
        str(entry.get("version", ""))
        for entry in answer.get("versions", [])
        if RELEASE.match(str(entry.get("version", "")))
    ]
    return max(releases, key=_release_key, default=None)


def find_outdated_updates(
    repo_root: Path, get: Fetch = fetch.get
) -> list[ProviderPinUpdate]:
    """Args:
        repo_root: repository root holding ``roles/``.
        get: reads an https URL.

    Returns:
        One update per pin behind its provider's newest release.
    """
    pins = collect_pins(repo_root)
    newest = {
        source: latest_release(source, get) for source in {p.source for p in pins}
    }
    return [
        ProviderPinUpdate(pin, newest[pin.source])
        for pin in pins
        if newest[pin.source]
        and _release_key(newest[pin.source]) > _release_key(pin.version)
    ]


def apply_updates(updates: list[ProviderPinUpdate]) -> list[Path]:
    """Args:
        updates: the result of :func:`find_outdated_updates`.

    Returns:
        Every ``versions.tf.json`` that changed.
    """
    changed = set()
    for update in updates:
        path = update.pin.path
        text = path.read_text(encoding="utf-8")  # nocheck: cache-read rewritten below
        pattern = re.compile(
            rf'("source":\s*"{re.escape(update.pin.source)}",\s*"version":\s*")'
            rf'{re.escape(update.pin.version)}"'
        )
        replaced, count = pattern.subn(rf'\g<1>{update.latest}"', text)
        if count:
            path.write_text(replaced, encoding="utf-8")
            changed.add(path)
    return sorted(changed)


def _runner(role_dir: Path) -> dict:
    services = load_yaml_str(read_text(str(role_dir / ROLE_FILE_META_SERVICES)))
    for entity in services.values():
        if isinstance(entity, dict) and "opentofu_version" in entity:
            return entity
    raise ValueError(f"{role_dir.name} pins no OpenTofu in meta/services.yml")


def host_architecture() -> str:
    """Returns:
        The architecture token of the machine running the update, mapped from
        its kernel machine name through ``HOST_ARCHITECTURE_BY_KERNEL``.

    Raises:
        ValueError: the map names no architecture for this machine.
    """
    by_kernel = load_yaml_str(read_text(str(GENERAL_VARS)))[ARCHITECTURE_BY_KERNEL]
    machine = platform.machine()
    if machine not in by_kernel:
        raise ValueError(
            f"{ARCHITECTURE_BY_KERNEL} maps no architecture for {machine!r}"
        )
    return str(by_kernel[machine])


def pinned_tofu(role_dir: Path, directory: Path, get: Fetch = fetch.get) -> Path:
    """Args:
        role_dir: the role whose ``meta/services.yml`` pins OpenTofu.
        directory: where the binary is unpacked.
        get: reads an https URL.

    Returns:
        The pinned ``tofu`` of this machine's architecture, its archive checked
        against the sum pinned for that architecture.
    """
    runner = _runner(role_dir)
    version = str(runner["opentofu_version"])
    architecture = host_architecture()
    url = str(runner[f"opentofu_url_{architecture}"]).replace("{version}", version)
    archive = get(url)
    if hashlib.sha256(archive).hexdigest() != runner[f"opentofu_sha256_{architecture}"]:
        raise ValueError(
            f"the OpenTofu {version} {architecture} archive does not match its pin"
        )
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        bundle.extract("tofu", directory, filter="data")
    binary = directory / "tofu"
    binary.chmod(0o755)
    return binary


def lock_roots(
    changed: list[Path], get: Fetch = fetch.get, run: Callable = subprocess.run
) -> list[Path]:
    """Args:
        changed: the ``versions.tf.json`` files :func:`apply_updates` changed.
        get: reads an https URL.
        run: runs a command, :func:`subprocess.run` by default.

    Returns:
        Every root whose lock file was rewritten for the new pins.
    """
    roots = sorted(
        {path.parent for path in changed if (path.parent / LOCK_FILE).is_file()}
    )
    locked = []
    for root in roots:
        parts = root.parts
        role_dir = Path(*parts[: parts.index("files")])
        runner = _runner(role_dir)
        with tempfile.TemporaryDirectory(prefix="opentofu-lock-") as scratch:
            binary = pinned_tofu(role_dir, Path(scratch), get)
            env = {
                **os.environ,
                "PATH": f"{binary.parent}{os.pathsep}{os.environ['PATH']}",
            }
            run(
                [
                    "bash",
                    str(role_dir / BUILD),
                    "lock",
                    str(role_dir / "files" / "opentofu"),
                    str(root),
                    *[str(platform) for platform in runner["opentofu_platforms"]],
                ],
                check=True,
                env=env,
            )
        locked.append(root)
    return locked


def stale_locks(repo_root: Path) -> list[str]:
    """Args:
        repo_root: repository root holding ``roles/``.

    Returns:
        One finding per pin its root's lock file does not record.
    """
    findings = []
    for pin in collect_pins(repo_root):
        lock = pin.path.parent / LOCK_FILE
        if not lock.is_file():
            continue
        text = lock.read_text(encoding="utf-8")  # nocheck: cache-read rewritten
        block = re.search(
            rf'^provider "registry\.opentofu\.org/{re.escape(pin.source)}" \{{\n'
            rf'\s*version\s*=\s*"([^"]+)"',
            text,
            re.MULTILINE,
        )
        if block is None or block.group(1) != pin.version:
            findings.append(f"{lock}: {pin.source} is not locked at {pin.version}")
    return findings
