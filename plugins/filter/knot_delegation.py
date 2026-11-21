from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleFilterError

NAMESERVER = "ns{index}.{zone}"
ACTIVE = "active"
SHA256 = 2
SHA256_HEX_LENGTH = 64
DS_FIELDS = ("key_tag", "algorithm", "hash_type", "value")
RETIRING = ("retire-active", "retire", "post-active", "revoke", "remove")
NO_READY_KEY = "no key ready for submission"
KNOTC_ERROR = re.compile(r"\berror\b", re.IGNORECASE)
DS_LINE = re.compile(
    r"^(?P<owner>\S+)\s+DS\s+(?P<tag>\d+)\s+(?P<algorithm>\d+)"
    r"\s+(?P<digest_type>\d+)\s+(?P<digest>[0-9A-Fa-f]+)$"
)


def _name(value: Any, what: str) -> str:
    """Args:
        value: a DNS name.
        what: what the name is, for the error.

    Returns:
        The name in lowercase without a trailing dot.

    Raises:
        AnsibleFilterError: the value is no non-empty string.
    """
    name = value.strip().rstrip(".").lower() if isinstance(value, str) else ""
    if not name:
        raise AnsibleFilterError(f"knot_delegation: the {what} {value!r} is no name")
    return name


def _glue(host: Any, value: Any) -> str:
    """Args:
        host: the knot host.
        value: its ``networks.internet.ip4``.

    Returns:
        The address its glue A carries.

    Raises:
        AnsibleFilterError: the value is no IPv4 address, or a loopback or
            unspecified one no resolver reaches.
    """
    try:
        address = ipaddress.IPv4Address(str(value).strip())
    except ValueError:
        address = None
    if address is None or address.is_loopback or address.is_unspecified:
        raise AnsibleFilterError(
            f"knot_delegation: {host} holds {value!r} in networks.internet.ip4, "
            f"no IPv4 address a resolver reaches"
        )
    return address.compressed


def knot_parent_candidates(zone: str) -> list[str]:
    """Args:
        zone: the knot subzone.

    Returns:
        Every proper suffix of the subzone with two labels or more, the
        longest first: the names its parent Cloudflare zone may carry.
    """
    labels = _name(zone, "subzone").split(".")
    return [".".join(labels[index:]) for index in range(1, len(labels) - 1)]


def knot_parent_zone(zone: str, found: Mapping) -> str:
    """Args:
        zone: the knot subzone.
        found: ``{candidate: zones}``, the ``result`` the Cloudflare zones API
            answered for each name of ``knot_parent_candidates``.

    Returns:
        The longest candidate the token reads as an active Cloudflare zone,
        so a deploy zone that is a Cloudflare zone of its own takes the
        records rather than a zone that delegates it away. A pending or moved
        zone answers no query, so a name with no active zone is no parent.

    Raises:
        AnsibleFilterError: a candidate went unasked, the longest candidate
            with an active zone carries a second zone of any status, which
            ``cloudflare_dns`` and ``cloudflare_records_converged`` cannot
            tell apart, or no candidate is an active zone.
    """
    zone = _name(zone, "subzone")
    candidates = knot_parent_candidates(zone)
    for candidate in candidates:
        if candidate not in found:
            raise AnsibleFilterError(
                f"knot_parent_zone: no Cloudflare answer for {candidate}"
            )
        named = [
            entry
            for entry in found[candidate]
            if isinstance(entry, Mapping) and entry.get("name") == candidate
        ]
        if not any(entry.get("status") == ACTIVE for entry in named):
            continue
        if len(named) > 1:
            raise AnsibleFilterError(
                f"knot_parent_zone: {len(named)} Cloudflare zones carry the name "
                f"{candidate}, {sorted(str(e.get('status')) for e in named)}, so "
                f"the parent of {zone} is ambiguous"
            )
        return candidate
    raise AnsibleFilterError(
        f"knot_parent_zone: the Cloudflare token reads no active zone of "
        f"{candidates}, so {zone} has no parent to delegate it"
    )


def _integer(key: Mapping, field: str) -> int:
    """Args:
        key: one key of ``keymgr -j <zone> list``.
        field: a numeric field of it.

    Returns:
        The field's value; a timer of ``0`` is unset.

    Raises:
        AnsibleFilterError: the field is no integer, as a timer printed in
            another format than Unix seconds is not.
    """
    value = key.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise AnsibleFilterError(
            f"knot_ksk: key {key.get('id')} of keymgr list has no integer {field!r}"
        )
    return value


def _current(key: Any, now: int) -> bool:
    """Args:
        key: one entry of ``keymgr -j <zone> list``.
        now: the current time in Unix seconds.

    Returns:
        True for a KSK that is ready and not retiring at ``now``.
    """
    if not isinstance(key, Mapping) or key.get("ksk") is not True:
        return False
    if key.get("trash") is True:
        return False
    if not 0 < _integer(key, "ready") <= now:
        return False
    return all(not 0 < _integer(key, timer) <= now for timer in RETIRING)


def knot_ksk(zone: str, keys: Any, now: int) -> dict:
    """Args:
        zone: the knot subzone.
        keys: the JSON ``keymgr -j <zone> list`` prints, as text or list.
        now: the current time in Unix seconds.

    Returns:
        ``tag`` and ``algorithm`` of the current KSK, the newest ready KSK
        that is not retiring: the only one outside a rollover, the new one
        during it. ``submitted`` is False while Knot keeps it ready, waiting
        for ``knotc zone-ksk-submitted`` to confirm its DS at the parent.

    Raises:
        AnsibleFilterError: the keys are no JSON list, no KSK is current, or
            two current KSKs turned ready at the same second.
    """
    zone = _name(zone, "subzone")
    if isinstance(keys, str):
        try:
            keys = json.loads(keys)
        except ValueError:
            raise AnsibleFilterError(
                f"knot_ksk: keymgr -j {zone} list printed no JSON"
            ) from None
    if not isinstance(keys, list):
        raise AnsibleFilterError(f"knot_ksk: keymgr -j {zone} list printed no list")
    current = [key for key in keys if _current(key, int(now))]
    if not current:
        raise AnsibleFilterError(f"knot_ksk: {zone} has no ready, unretired KSK")
    newest = max(key["ready"] for key in current)
    chosen = [key for key in current if key["ready"] == newest]
    if len(chosen) != 1:
        raise AnsibleFilterError(
            f"knot_ksk: {zone} has {len(chosen)} KSKs ready since {newest}: "
            f"{sorted(key.get('tag') for key in chosen)}"
        )
    (ksk,) = chosen
    return {
        "tag": _integer(ksk, "tag"),
        "algorithm": _integer(ksk, "algorithm"),
        "submitted": 0 < _integer(ksk, "active") <= int(now),
    }


def knot_ds(zone: str, ksk: Mapping, ds: str) -> dict:
    """Args:
        zone: the knot subzone.
        ksk: the current KSK ``knot_ksk`` returns.
        ds: the text ``keymgr <zone> ds`` prints, one DS per KSK and digest.

    Returns:
        ``key_tag``, ``algorithm``, ``hash_type`` and ``value`` of the SHA-256
        DS of that KSK, the digest in uppercase.

    Raises:
        AnsibleFilterError: a malformed line or a line of another owner, or
            not exactly one SHA-256 DS of the KSK.
    """
    zone = _name(zone, "subzone")
    want = (ksk["tag"], ksk["algorithm"], SHA256)
    digests = set()
    tags = set()
    for line in [text.strip() for text in str(ds).splitlines() if text.strip()]:
        match = DS_LINE.match(line)
        if match is None:
            raise AnsibleFilterError(f"knot_ds: keymgr ds printed {line!r}")
        if _name(match["owner"], "DS owner") != zone:
            raise AnsibleFilterError(
                f"knot_ds: keymgr ds of {zone} printed a DS of {match['owner']}"
            )
        tags.add(int(match["tag"]))
        have = (int(match["tag"]), int(match["algorithm"]), int(match["digest_type"]))
        if have == want:
            digests.add(match["digest"].upper())
    if len(digests) != 1 or len(next(iter(digests))) != SHA256_HEX_LENGTH:
        raise AnsibleFilterError(
            f"knot_ds: keymgr ds of {zone} names {len(digests)} SHA-256 DS of the "
            f"current KSK {want[0]}, expected one; it names the key tags {sorted(tags)}"
        )
    return dict(zip(DS_FIELDS, (*want, digests.pop()), strict=True))


def knot_submission(result: Mapping) -> str:
    """Args:
        result: the registered result of ``knotc zone-ksk-submitted <zone>``.

    Returns:
        ``unready`` when Knot reports no KSK ready for submission, ``failed``
        on any other error, an exit status other than 0 or an ``error`` in
        its output, and ``confirmed`` otherwise.
    """
    output = f"{result.get('stdout')}\n{result.get('stderr')}"
    if NO_READY_KEY in output:
        return "unready"
    if result.get("rc") != 0 or KNOTC_ERROR.search(output):
        return "failed"
    return "confirmed"


def knot_delegation(zone: str, parent: str, addresses: Mapping, ds: Mapping) -> list:
    """Args:
        zone: the knot subzone.
        parent: the Cloudflare zone that delegates it, ``knot_parent_zone``.
        addresses: ``{host: networks.internet.ip4}`` of the knot group, the
            primary first, in the order ``templates/zone.j2`` of
            ``svc-dns-knot`` numbers them.
        ds: the DS fields ``knot_ds`` returns.

    Returns:
        The ``cloudflare_records`` entries of the delegation: per host one NS
        ``ns<n>.<zone>`` and its glue A, then the DS. No glue AAAA, as knot
        listens on IPv4 only.

    Raises:
        AnsibleFilterError: the zone is not below the parent, no host is
            given, a host has no IPv4 address a resolver reaches, or the DS
            lacks a field.
    """
    zone = _name(zone, "subzone")
    parent = _name(parent, "parent zone")
    if not zone.endswith(f".{parent}"):
        raise AnsibleFilterError(f"knot_delegation: {zone} is not below {parent}")
    if not addresses:
        raise AnsibleFilterError(f"knot_delegation: {zone} has no knot host")
    if not isinstance(ds, Mapping) or any(field not in ds for field in DS_FIELDS):
        raise AnsibleFilterError(f"knot_delegation: the DS of {zone} lacks {DS_FIELDS}")
    records = []
    for index, (host, value) in enumerate(addresses.items(), start=1):
        target = NAMESERVER.format(index=index, zone=zone)
        records += [
            {"zone": parent, "type": "NS", "name": zone, "value": target},
            {
                "zone": parent,
                "type": "A",
                "name": target,
                "content": _glue(host, value),
                "proxied": False,
                "solo": True,
            },
        ]
    records.append(
        {
            "zone": parent,
            "type": "DS",
            "name": zone,
            **{field: ds[field] for field in DS_FIELDS},
            "solo": True,
        }
    )
    return records


class FilterModule:
    def filters(self):
        return {
            "knot_delegation": knot_delegation,
            "knot_ds": knot_ds,
            "knot_ksk": knot_ksk,
            "knot_parent_candidates": knot_parent_candidates,
            "knot_parent_zone": knot_parent_zone,
            "knot_submission": knot_submission,
        }
