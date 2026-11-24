from __future__ import annotations

import base64
import secrets

SIZE_KEYS = ("vcpus", "memory_mib", "disk_gib")
KEY_TYPE = "ssh-ed25519"
KEY_BYTES = 32


class DrillError(Exception):
    pass


def public_key():
    """
    Returns:
        A fresh login key line in the ed25519 OpenSSH form
        ``sshEd25519PublicLine`` of the Playwright personas writes, its 32 key
        bytes random, so no private half exists.
    """
    raw = secrets.token_bytes(KEY_BYTES)
    blob = b"".join(
        len(part).to_bytes(4, "big") + part for part in (KEY_TYPE.encode("ascii"), raw)
    )
    return f"{KEY_TYPE} {base64.b64encode(blob).decode('ascii')}"


def order_values(order, catalog, key):
    """
    Args:
        order: the survey ``BKP_TEST_WORKSPACE_ORDER`` holds.
        catalog: the provider catalog the provision runner checks a line
            against.
        key: the OpenSSH public key of the first login.

    Returns:
        The root inputs of the order line: the smallest size of the catalog
        by vCPUs, memory and disk, ties broken by flavor and size name, in
        the alphabetically first region of that flavor that names a host.
    """
    for flavor, entry in catalog.items():
        for size, resources in entry["sizes"].items():
            missing = [field for field in SIZE_KEYS if field not in resources]
            if missing:
                raise DrillError(
                    f"size {size} of flavor {flavor} names no {', '.join(missing)}"
                )
    offers = sorted(
        ([entry["sizes"][size][field] for field in SIZE_KEYS], flavor, size, region)
        for flavor, entry in catalog.items()
        for size in entry["sizes"]
        for region, place in entry["regions"].items()
        if place.get("host")
    )
    if not offers:
        raise DrillError("the catalog offers no region that names a host")
    _, flavor, size, region = offers[0]
    name = f"{order['SALES_ORDER']}-{order['LINE']}"
    return {
        "name": name,
        "flavor": flavor,
        "size": size,
        "region": region,
        "ssh_public_key": key,
        "dns_label": name.lower(),
    }
