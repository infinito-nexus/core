from __future__ import annotations

import json
from collections import Counter
from http.client import HTTPException
from typing import Any
from urllib.parse import urlencode

from ansible.errors import AnsibleActionFail
from ansible.module_utils.common.validation import check_type_int
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.module_utils.urls import ConnectionError as UrlsConnectionError
from ansible.module_utils.urls import open_url
from ansible.plugins.action import ActionBase

API = "https://api.cloudflare.com/client/v4"
REVIEWED_COMMUNITY_GENERAL = "14.0.0"
PAGE_SIZE = 5000
ARGUMENTS = frozenset({"api_token", "records", "timeout"})
JUDGED_TYPES = ("A", "AAAA", "CNAME", "MX", "TXT", "SRV")
LOWERED_TYPES = ("CNAME", "MX", "SRV")
PROXIABLE_TYPES = ("A", "AAAA", "CNAME")
APPLY_TTL = 1
APPLY_PROXIED = False
APPLY_SOLO = False
APPLY_STATE = "present"
APPLY_MX_PRIORITY = 10
MODULE_PRIORITY = 1
MODULE_PROXIED = False
READ_FAILURES = (
    OSError,
    ValueError,
    KeyError,
    TypeError,
    HTTPException,
    UrlsConnectionError,
)


def _get(path: str, token: str, timeout: int) -> dict[str, Any]:
    """
    Args:
        path: API path below ``API``, query string included.
        token: Cloudflare API token, sent in the bearer header only.
        timeout: seconds one socket operation may stall.

    Returns:
        The decoded answer; raises ``ValueError`` when Cloudflare reports no success.
    """
    response = open_url(
        API + path,
        method="GET",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        timeout=timeout,
    )
    answer = json.loads(response.read())
    if not isinstance(answer, dict) or answer.get("success") is not True:
        errors = answer.get("errors") if isinstance(answer, dict) else answer
        raise ValueError(f"GET {path} answered without success: {errors}")
    return answer


def zone_records(zone: str, token: str, timeout: int) -> list[dict[str, Any]]:
    """
    Args:
        zone: Cloudflare zone name.
        token: Cloudflare API token.
        timeout: seconds one socket operation may stall.

    Returns:
        Every DNS record of the zone, across all pages; raises ``ValueError``
        unless exactly one zone carries the name.
    """
    zones = _get("/zones?" + urlencode({"name": zone}), token, timeout)["result"]
    if len(zones) != 1:
        raise ValueError(f"{len(zones)} Cloudflare zones match {zone}")
    records: list[dict[str, Any]] = []
    page = 1
    while True:
        answer = _get(
            f"/zones/{zones[0]['id']}/dns_records?"
            + urlencode({"page": page, "per_page": PAGE_SIZE}),
            token,
            timeout,
        )
        records.extend(answer["result"])
        if page >= int(answer["result_info"]["total_pages"]):
            return records
        page += 1


def _int(value: Any) -> int | None:
    """
    Args:
        value: a record field the module reads as ``int``.

    Returns:
        The integer ansible-core's ``check_type_int`` makes of the field, or
        ``None`` when it is a boolean or ``check_type_int`` rejects it.
    """
    if isinstance(value, bool):
        return None
    try:
        return check_type_int(value)
    except (TypeError, OverflowError):
        return None


def _bool(value: Any) -> bool | None:
    """
    Args:
        value: a record field the module reads as ``bool``.

    Returns:
        The boolean, or ``None`` when the field is not one.
    """
    try:
        return boolean(value, strict=True)
    except TypeError:
        return None


def _owner(record: Any) -> tuple[str, str, str] | None:
    """
    Args:
        record: one ``cloudflare_records`` entry.

    Returns:
        ``(zone, type, name)`` of the record set the module edits for the
        entry, normalised as the module normalises them, or ``None`` when the
        entry names no A, AAAA, CNAME, MX, TXT or SRV record set.
    """
    if not isinstance(record, dict):
        return None
    rtype = record.get("type")
    zone = record.get("zone")
    name = record.get("name")
    if rtype not in JUDGED_TYPES:
        return None
    if not all(isinstance(v, str) and v for v in (zone, name)):
        return None
    zone = zone.lower()
    fqdn = name.lower()
    if fqdn == "@":
        fqdn = zone
    if not fqdn.endswith(zone):
        fqdn = f"{fqdn}.{zone}"
    if rtype == "SRV":
        service = record.get("service")
        proto = record.get("proto")
        if not all(isinstance(v, str) and v for v in (service, proto)):
            return None
        service = service.lower()
        proto = proto.lower()
        if not service.startswith("_"):
            service = f"_{service}"
        if not proto.startswith("_"):
            proto = f"_{proto}"
        fqdn = f"{service}.{proto}.{fqdn}"
    return zone, rtype, fqdn


def _hazardous(record: dict[str, Any]) -> bool:
    """
    Args:
        record: one ``cloudflare_records`` entry ``_owner`` keyed.

    Returns:
        True when the module run for the entry may delete records of its
        record set: it is solo, its solo flag reads as no boolean, or it is
        not in state present.
    """
    solo = _bool(record["solo"]) if "solo" in record else APPLY_SOLO
    return solo is not False or record.get("state", APPLY_STATE) != "present"


def expected(record: Any) -> dict[str, Any] | None:
    """
    Args:
        record: one ``cloudflare_records`` entry as ``tasks/apply.yml`` of
            ``sys-dns-cloudflare-records`` hands it to
            ``community.general.cloudflare_dns``.

    Returns:
        ``type``, ``name``, ``content``, ``ttl``, ``priority``, ``proxied``,
        ``data`` and ``solo`` of the record the module converges the entry
        to, or ``None`` unless the entry is a present A, AAAA, CNAME, MX, TXT
        or SRV record whose every field reads as the module reads it.
    """
    owner = _owner(record)
    if owner is None:
        return None
    _zone, rtype, fqdn = owner
    if record.get("state", APPLY_STATE) != "present":
        return None
    raw = record.get("content" if rtype in ("A", "AAAA") else "value")
    if not (isinstance(raw, str) and raw):
        return None

    if rtype in LOWERED_TYPES:
        content = raw.rstrip(".").lower()
    elif rtype == "AAAA":
        content = raw.lower()
    else:
        content = raw

    ttl = _int(record["ttl"]) if "ttl" in record else APPLY_TTL
    solo = _bool(record["solo"]) if "solo" in record else APPLY_SOLO
    if rtype in ("A", "AAAA"):
        proxied = _bool(record["proxied"]) if "proxied" in record else APPLY_PROXIED
    elif rtype == "CNAME":
        proxied = MODULE_PROXIED
    else:
        proxied = None
    if rtype == "MX":
        priority = (
            _int(record["priority"]) if "priority" in record else APPLY_MX_PRIORITY
        )
    elif rtype == "SRV":
        priority = _int(record.get("priority"))
    else:
        priority = MODULE_PRIORITY
    if None in (ttl, solo, priority) or (rtype in PROXIABLE_TYPES and proxied is None):
        return None

    data = None
    if rtype == "SRV":
        weight = _int(record.get("weight"))
        port = _int(record.get("port"))
        if weight is None or port is None:
            return None
        data = {"target": content, "port": port, "weight": weight, "priority": priority}

    return {
        "type": rtype,
        "name": fqdn,
        "content": content,
        "ttl": ttl,
        "priority": priority,
        "proxied": proxied,
        "data": data,
        "solo": solo,
    }


def _srv_key(rr: dict[str, Any]) -> tuple[Any, Any, str] | None:
    """
    Args:
        rr: one DNS record as the Cloudflare API returns it.

    Returns:
        ``(weight, port, target)`` the module matches SRV records by, or
        ``None`` when the record carries no SRV data.
    """
    data = rr.get("data")
    if not isinstance(data, dict):
        return None
    return (
        data.get("weight"),
        data.get("port"),
        str(data.get("target")).rstrip(".").lower(),
    )


def _unquoted(content: Any) -> str:
    """
    Args:
        content: a TXT record content.

    Returns:
        The content without one pair of surrounding double quotes.
    """
    text = str(content)
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    return text


def _identity(want: dict[str, Any]) -> Any:
    """
    Args:
        want: the record ``expected`` returns.

    Returns:
        The key the module finds the record by within its record set:
        ``(weight, port, target)`` for SRV, ``()`` for CNAME, whose record
        set holds one record, and the case-folded content otherwise, TXT
        without one pair of surrounding quotes.
    """
    if want["type"] == "SRV":
        return (want["data"]["weight"], want["data"]["port"], want["content"])
    if want["type"] == "CNAME":
        return ()
    if want["type"] == "TXT":
        return _unquoted(want["content"]).lower()
    return want["content"].lower()


def converged(want: dict[str, Any], zone_rrs: list[Any]) -> bool:
    """
    Args:
        want: the record ``expected`` returns.
        zone_rrs: every DNS record of the record's zone.

    Returns:
        True only when the zone already holds exactly the record the module
        would leave behind, so the module call would change nothing.
    """
    same_name = [
        rr
        for rr in zone_rrs
        if isinstance(rr, dict)
        and rr.get("type") == want["type"]
        and str(rr.get("name")).lower() == want["name"]
    ]
    key = _identity(want)
    if want["type"] == "SRV":
        matches = [rr for rr in same_name if _srv_key(rr) == key]
    elif want["type"] == "CNAME":
        matches = same_name
    elif want["type"] == "TXT":
        matches = [
            rr for rr in same_name if _unquoted(rr.get("content")).lower() == key
        ]
    else:
        matches = [rr for rr in same_name if str(rr.get("content")).lower() == key]
    if len(matches) != 1 or (want["solo"] and len(same_name) != 1):
        return False
    rr = matches[0]
    if rr.get("name") != want["name"] or rr.get("ttl") != want["ttl"]:
        return False
    if "priority" in rr and rr["priority"] != want["priority"]:
        return False
    if "comment" not in rr or rr["comment"] is not None or rr.get("tags") != []:
        return False
    if want["type"] in PROXIABLE_TYPES and (
        "proxied" not in rr or rr["proxied"] != want["proxied"]
    ):
        return False
    if want["type"] == "SRV":
        return rr.get("data") == want["data"]
    return rr.get("content") == want["content"]


def split(
    records: list[Any], token: str, timeout: int
) -> tuple[list[Any], list[str], list[str]]:
    """
    Args:
        records: the ``cloudflare_records`` list.
        token: Cloudflare API token.
        timeout: seconds one socket operation may stall.

    Returns:
        ``(pending, converged, warnings)``: the entries the module still has
        to apply, in their original order, the labels of the entries the
        zone already holds as declared, and one warning per zone whose
        records could not be read, whose entries all stay pending. Every
        entry of a record set declared more than once stays pending when
        one of its entries is hazardous, ``expected`` cannot judge one of
        them, whose apply may still write the record set, or two of them
        declare the record the module finds by one ``_identity`` differently,
        since each verdict alone would let the last entry's apply undo the
        other's.
    """
    owners = [_owner(record) for record in records]
    wants = [expected(record) for record in records]
    sizes = Counter(owner for owner in owners if owner is not None)
    declared: dict[tuple[Any, Any], dict[str, Any]] = {}
    blocked: set[tuple[str, str, str]] = set()
    for owner, record, want in zip(owners, records, wants, strict=True):
        if owner is None or sizes[owner] < 2:
            continue
        if (
            want is None
            or _hazardous(record)
            or declared.setdefault((owner, _identity(want)), want) != want
        ):
            blocked.add(owner)
    zones: dict[str, list[Any] | None] = {}
    pending: list[Any] = []
    labels: list[str] = []
    warnings: list[str] = []
    for owner, record, candidate in zip(owners, records, wants, strict=True):
        want = None if owner in blocked else candidate
        if want is None:
            pending.append(record)
            continue
        zone = owner[0]
        if zone not in zones:
            try:
                zones[zone] = zone_records(zone, token, timeout)
            except READ_FAILURES as error:
                zones[zone] = None
                warnings.append(
                    f"Cloudflare zone {zone}: its records could not be read "
                    f"({error}), so every record of it goes through cloudflare_dns"
                )
        if zones[zone] is not None and converged(want, zones[zone]):
            labels.append(f"{want['type']} {want['name']}")
        else:
            pending.append(record)
    return pending, labels, warnings


class ActionModule(ActionBase):
    TRANSFERS_FILES = False

    def run(
        self, tmp: Any = None, task_vars: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Args:
            tmp: unused, kept for the ``ActionBase`` signature.
            task_vars: the task's variables.

        Returns:
            The action result with ``pending`` and ``converged``.
        """
        result = super().run(tmp, task_vars)
        args = self._task.args or {}
        unexpected = sorted(set(args) - ARGUMENTS)
        missing = sorted(ARGUMENTS - set(args))
        if unexpected or missing:
            raise AnsibleActionFail(
                "cloudflare_records_converged: takes exactly api_token, records "
                f"and timeout; unknown {unexpected}, missing {missing}"
            )
        records = args["records"]
        if not isinstance(records, list):
            raise AnsibleActionFail(
                "cloudflare_records_converged: records must be a list"
            )
        timeout = _int(args["timeout"])
        if timeout is None:
            raise AnsibleActionFail(
                "cloudflare_records_converged: timeout must be an integer"
            )

        pending, labels, warnings = split(records, str(args["api_token"]), timeout)
        result.update(changed=False, pending=pending, converged=labels)
        if warnings:
            result["warnings"] = warnings
        return result
