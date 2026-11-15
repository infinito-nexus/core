from __future__ import annotations

import re

from ansible.errors import AnsibleFilterError

ISO = re.compile(r"proxmox-ve_(\d+\.\d+)-\d+\.iso")
PACKAGE = re.compile(r"(\d+\.\d+)\.\d+")
NESTED_ON = frozenset({"y", "1"})


def proxmox_iso_release(file: str) -> str:
    """Args:
        file: file name of the installer ISO, such as ``proxmox-ve_9.2-1.iso``.

    Returns:
        The Proxmox VE release the ISO installs, such as ``9.2``.
    """
    match = ISO.fullmatch(str(file))
    if not match:
        raise AnsibleFilterError(
            f"services.proxmox.ve.iso.file {file!r} is no proxmox-ve_<release>-<build>.iso"
        )
    return match.group(1)


def proxmox_package_release(version: str) -> str:
    """Args:
        version: pinned pve-manager version, such as ``9.2.26``.

    Returns:
        The Proxmox VE release of that version, such as ``9.2``.
    """
    match = PACKAGE.fullmatch(str(version))
    if not match:
        raise AnsibleFilterError(
            f"services.proxmox.ve.packages.pve-manager {version!r} is no <major>.<minor>.<patch>"
        )
    return match.group(1)


def proxmox_nested(parameters: str) -> bool:
    """Args:
        parameters: the contents of ``/sys/module/kvm_intel/parameters/nested``
            and ``/sys/module/kvm_amd/parameters/nested``, empty when neither
            module is loaded.

    Returns:
        True when one of them reads ``Y`` or ``1``, so guests of the host run
        their own guests with KVM.
    """
    return any(
        line.strip().lower() in NESTED_ON for line in str(parameters).splitlines()
    )


class FilterModule:
    def filters(self):
        return {
            "proxmox_iso_release": proxmox_iso_release,
            "proxmox_nested": proxmox_nested,
        }
