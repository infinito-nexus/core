from __future__ import annotations

import hashlib
import json

from plugins.filter import knot_delegation as delegation

ZONE = "ws.example.org"
OWNER = f"{ZONE}."
PARENT = "example.org"
NOW = 1_800_000_000
HOUR = 3600
ALGORITHM = 13
FIRST_KSK = 2371
SECOND_KSK = 40002
ZSK_TAG = 61234
HOSTS = {
    "knot-primary": {"ip4": "192.0.2.1", "ip6": "2001:db8::1"},
    "knot-secondary-a": {"ip4": "192.0.2.2", "ip6": "2001:db8::2"},
    "knot-secondary-b": {"ip4": "192.0.2.3", "ip6": "2001:db8::3"},
}


def key(tag, ksk, timers):
    """Args:
        tag: the key tag.
        ksk: whether the key is a KSK.
        timers: the timers that are set, in Unix seconds.

    Returns:
        One key as ``keymgr -j <zone> list`` prints it, every other timer 0.
    """
    unset = dict.fromkeys(
        ("created", "pre-active", "publish", "ready", "active", *delegation.RETIRING),
        0,
    )
    return {
        "zone": OWNER,
        "id": f"key-{tag}",
        "ksk": ksk,
        "zsk": not ksk,
        "tag": tag,
        "algorithm": ALGORITHM,
        "size": 256,
        "public-only": False,
        **unset,
        **timers,
    }


ZSK = key(ZSK_TAG, False, {"publish": NOW - HOUR, "active": NOW - HOUR})
NEW_ZONE_KSK = key(FIRST_KSK, True, {"publish": NOW - HOUR, "ready": NOW - HOUR})
FRESH_KSK = key(FIRST_KSK, True, {"publish": NOW - 60, "ready": NOW - 60})
OLD_KSK = key(
    FIRST_KSK,
    True,
    {"publish": NOW - 9 * HOUR, "ready": NOW - 9 * HOUR, "active": NOW - 8 * HOUR},
)
ROLLED_KSK = key(SECOND_KSK, True, {"publish": NOW - 2 * HOUR, "ready": NOW - HOUR})


def digest(tag, digest_type):
    """Args:
        tag: a key tag.
        digest_type: 2 for SHA-256, 4 for SHA-384.

    Returns:
        A stable lowercase digest of that length, as keymgr prints it.
    """
    algorithm = {2: hashlib.sha256, 4: hashlib.sha384}[digest_type]
    return algorithm(f"{ZONE}/{tag}".encode()).hexdigest()


def ds_output(owner, *tags):
    """Args:
        owner: the owner name of every line.
        tags: the key tags of the KSKs keymgr prints a DS for.

    Returns:
        The text of ``keymgr <zone> ds``: a SHA-256 and a SHA-384 DS per KSK.
    """
    return "".join(
        f"{owner} DS {tag} {ALGORITHM} {digest_type} {digest(tag, digest_type)}\n"
        for tag in tags
        for digest_type in (2, 4)
    )


def addresses(hosts):
    return {host: internet["ip4"] for host, internet in hosts.items()}


def ds_record():
    ksk = delegation.knot_ksk(ZONE, json.dumps([ZSK, NEW_ZONE_KSK]), NOW)
    return delegation.knot_ds(ZONE, ksk, ds_output(OWNER, FIRST_KSK))


def build(hosts):
    """Args:
        hosts: ``{host: networks.internet}`` of the knot group.

    Returns:
        The delegation records the knot filters build for a new zone, whose
        only KSK is ``FIRST_KSK``.
    """
    return delegation.knot_delegation(ZONE, PARENT, addresses(hosts), ds_record())


def active(*names):
    return tuple((name, "active") for name in names)


def cloudflare_zones(name, zones):
    """Args:
        name: the ``name`` the Cloudflare zones API is asked for.
        zones: ``(name, status)`` of every zone the token reads.

    Returns:
        The ``result`` of that request.
    """
    return [
        {"id": f"zone-{index}", "name": zone, "status": status}
        for index, (zone, status) in enumerate(zones)
        if zone == name
    ]
