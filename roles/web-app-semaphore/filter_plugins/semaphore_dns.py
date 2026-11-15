from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleFilterError

from utils.cache import ROLES_DIR

FILES = ROLES_DIR / "web-app-semaphore" / "files" / "opentofu"
MODULES = FILES / "modules"
FLAVORS = tuple(
    sorted(path.name.removeprefix("dns-") for path in MODULES.glob("dns-*"))
)
RECORD_TYPES = ("A", "AAAA", "CNAME", "TXT")
HOSTED_ZONE = "arn:aws:route53:::hostedzone/{zone_id}"
CHANGES = "arn:aws:route53:::change/*"
CREDENTIALS_PATH = "secrets.credentials"
LIVE_CREDENTIALS = {
    "knot": (),
    "route53": ("route53_access_key_id", "route53_secret_access_key"),
    "cloudflare": ("cloudflare_zone_tokens",),
}
ROUTE53_ADMIN = ("platform", "workspaces/route53")
ROUTE53_FIELDS = {
    "access_key_id": "route53_access_key_id",
    "secret_access_key": "route53_secret_access_key",
}
ZONE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)


def semaphore_cloudflare_pool(credentials: Mapping) -> dict[str, str]:
    """Args:
        credentials: the DNS credentials of ``secrets.credentials``.

    Returns:
        ``{zone: token}`` of ``cloudflare_zone_tokens`` in placement order.

    Raises:
        AnsibleFilterError: the value is no object from lowercase zones to
            tokens, or two zones share a token; no message names a token.
    """
    raw = credentials.get("cloudflare_zone_tokens") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            raise AnsibleFilterError(
                f"{CREDENTIALS_PATH}.cloudflare_zone_tokens is no JSON object"
            ) from None
    if not isinstance(raw, Mapping):
        raise AnsibleFilterError(
            f"{CREDENTIALS_PATH}.cloudflare_zone_tokens is no object from zone to token"
        )
    tokens = {}
    for zone, token in raw.items():
        if not ZONE.match(str(zone)) or not isinstance(token, str) or not token:
            raise AnsibleFilterError(
                f"{CREDENTIALS_PATH}.cloudflare_zone_tokens: {str(zone)!r} is no "
                f"lowercase zone name with a token"
            )
        tokens[str(zone)] = token
    shared = sorted(z for z in tokens if list(tokens.values()).count(tokens[z]) > 1)
    if shared:
        raise AnsibleFilterError(
            f"{CREDENTIALS_PATH}.cloudflare_zone_tokens: the zones {shared} share a token"
        )
    return tokens


def semaphore_dns_live(dns: Mapping, credentials: Mapping) -> dict:
    """Args:
        dns: ``services.semaphore.workspaces.dns`` of the deployment.
        credentials: the DNS credentials of ``secrets.credentials``; a
            credential anywhere else counts as missing.

    Returns:
        ``{"run": bool, "missing": [key], "message": str}``: whether the
        flavor's live checks can run, and the credentials they lack.
    """
    flavor = semaphore_dns_flavor(dns.get("flavor"))
    present = {
        "route53_access_key_id": bool(credentials.get("route53_access_key_id")),
        "route53_secret_access_key": bool(credentials.get("route53_secret_access_key")),
        "cloudflare_zone_tokens": bool(semaphore_cloudflare_pool(credentials)),
    }
    missing = [
        f"{CREDENTIALS_PATH}.{key}"
        for key in LIVE_CREDENTIALS[flavor]
        if not present[key]
    ]
    message = (
        f"dns flavor {flavor}: live checks run"
        if not missing
        else f"dns flavor {flavor}: live checks not run, missing {', '.join(missing)}"
    )
    return {"run": not missing, "missing": missing, "message": message}


def _write(mount: str, path: str, data: dict) -> dict:
    return {"mount": mount, "path": path, "data": data}


def _dns_spec(flavor: str) -> dict:
    spec = json.loads((FILES / "credentials.json").read_text(encoding="utf-8"))
    return spec["dns"][flavor]


def semaphore_route53_admin_missing(record: Mapping) -> list[str]:
    """Args:
        record: the fields of ``platform/data/workspaces/route53``, ``{}``
            when it holds no version.

    Returns:
        The fields of the AWS credential that creates the workspace IAM users
        which the record lacks or holds empty, never a value.
    """
    return [field for field in ROUTE53_FIELDS if not record.get(field)]


def semaphore_route53_held_key(record: Mapping) -> str:
    """Args:
        record: the fields of ``tenant/data/ws-<id>-provision/dns``.

    Returns:
        The access key id the record holds beside its secret, in the fields
        ``credentials.json`` reads for route53; empty when either is missing.
    """
    env = _dns_spec("route53")["env"]
    key, secret = env["AWS_ACCESS_KEY_ID"], env["AWS_SECRET_ACCESS_KEY"]
    return str(record[key]) if record.get(key) and record.get(secret) else ""


def semaphore_route53_record(record: Mapping, user: Mapping, policy: Mapping) -> dict:
    """Args:
        record: the fields of ``tenant/data/ws-<id>-provision/dns`` before apply.
        user: what ``semaphore_route53_user`` returned for ``present``.
        policy: the rendered policy of the workspace's IAM user.

    Returns:
        The record with ``policy`` as its field ``policy`` and a minted key in
        the fields ``credentials.json`` reads for route53; a kept key stays.

    Raises:
        AnsibleFilterError: ``user`` minted a key without its secret.
    """
    env = _dns_spec("route53")["env"]
    minted = {}
    if user["minted"]:
        if not user["access_key_id"] or not user["secret_access_key"]:
            raise AnsibleFilterError(
                "semaphore_route53_record: the minted key arrived without its "
                "id or secret"
            )
        minted = {
            env["AWS_ACCESS_KEY_ID"]: user["access_key_id"],
            env["AWS_SECRET_ACCESS_KEY"]: user["secret_access_key"],
        }
    return {**record, **minted, "policy": policy}


def semaphore_dns_writes(credentials: Mapping, dns: Mapping) -> list[dict]:
    """Args:
        credentials: the DNS credentials of ``secrets.credentials``.
        dns: ``services.semaphore.workspaces.dns`` of the deployment.

    Returns:
        One ``{mount, path, data}`` per KV v2 secret the deploy writes
        into OpenBao: the Route 53 pair at ``platform/data/workspaces/route53``
        and each zone token at the path ``credentials.json`` reads it from.
        Empty while the flavor's live checks do not run.
    """
    if not semaphore_dns_live(dns, credentials)["run"]:
        return []
    flavor = semaphore_dns_flavor(dns.get("flavor"))
    if flavor == "route53":
        data = {field: str(credentials[key]) for field, key in ROUTE53_FIELDS.items()}
        return [_write(*ROUTE53_ADMIN, data)]
    if flavor == "cloudflare":
        cloudflare = _dns_spec("cloudflare")
        mount, _, path = cloudflare["path"].partition("/data/")
        (field,) = cloudflare["env"].values()
        return [
            _write(mount, path.format(zone=zone), {field: token})
            for zone, token in semaphore_cloudflare_pool(credentials).items()
        ]
    return []


def semaphore_dns_flavor(flavor: Any) -> str:
    """Args:
        flavor: ``services.semaphore.workspaces.dns.flavor``.

    Returns:
        The flavor, once a module ``dns-<flavor>`` ships for it.

    Raises:
        AnsibleFilterError: no module ships for the flavor.
    """
    if flavor not in FLAVORS:
        raise AnsibleFilterError(
            f"semaphore_dns_flavor: services.semaphore.workspaces.dns.flavor is "
            f"{flavor!r}, expected one of {', '.join(FLAVORS)}"
        )
    return str(flavor)


def semaphore_route53_policy(workspace: str, zone_id: str, subzone: str) -> dict:
    """Args:
        workspace: ``ws-<id>``.
        zone_id: the hosted zone of the subzone.
        subzone: ``services.semaphore.workspaces.dns.zone``.

    Returns:
        The IAM policy of the workspace's user: ``ChangeResourceRecordSets``
        on names below ``<workspace>.<subzone>`` and the types A, AAAA, CNAME
        and TXT,
        ``GetHostedZone`` and ``ListResourceRecordSets`` on the hosted zone and
        ``GetChange`` on its changes.
    """
    for name, value in (
        ("workspace", workspace),
        ("zone_id", zone_id),
        ("subzone", subzone),
    ):
        if not value or "*" in value:
            raise AnsibleFilterError(
                f"semaphore_route53_policy: {name} {value!r} is empty or a wildcard"
            )
    zone = HOSTED_ZONE.format(zone_id=zone_id)
    names = f"*.{workspace}.{subzone}".lower().rstrip(".")
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ChangeOwnNames",
                "Effect": "Allow",
                "Action": "route53:ChangeResourceRecordSets",
                "Resource": zone,
                "Condition": {
                    "ForAllValues:StringLike": {
                        "route53:ChangeResourceRecordSetsNormalizedRecordNames": [names]
                    },
                    "ForAllValues:StringEquals": {
                        "route53:ChangeResourceRecordSetsRecordTypes": list(
                            RECORD_TYPES
                        )
                    },
                },
            },
            {
                "Sid": "ReadZone",
                "Effect": "Allow",
                "Action": ["route53:GetHostedZone", "route53:ListResourceRecordSets"],
                "Resource": zone,
            },
            {
                "Sid": "ReadChange",
                "Effect": "Allow",
                "Action": "route53:GetChange",
                "Resource": CHANGES,
            },
        ],
    }


def semaphore_cloudflare_zone(
    credentials: Mapping, records: Mapping[str, int], limit: int
) -> str:
    """Args:
        credentials: the DNS credentials of ``secrets.credentials``; the keys
            of ``cloudflare_zone_tokens`` are the pool in placement order.
        records: ``{zone: number of records}`` the zone holds now.
        limit: the record limit of a zone on the deployment's Cloudflare plan.

    Returns:
        The first zone below the record limit.

    Raises:
        AnsibleFilterError: the pool is empty, two zones share a token, a zone
            lacks a count, or every zone is full.
    """
    zones = list(semaphore_cloudflare_pool(credentials))
    if not zones:
        raise AnsibleFilterError(
            f"semaphore_cloudflare_zone: {CREDENTIALS_PATH}.cloudflare_zone_tokens "
            f"names no zone"
        )
    missing = [zone for zone in zones if zone not in records]
    if missing:
        raise AnsibleFilterError(
            f"semaphore_cloudflare_zone: no record count for {missing}"
        )
    for zone in zones:
        if records[zone] < int(limit):
            return zone
    raise AnsibleFilterError(
        f"semaphore_cloudflare_zone: every zone of the pool is full: {zones}"
    )


class FilterModule:
    def filters(self):
        return {
            "semaphore_cloudflare_pool": semaphore_cloudflare_pool,
            "semaphore_cloudflare_zone": semaphore_cloudflare_zone,
            "semaphore_dns_flavor": semaphore_dns_flavor,
            "semaphore_dns_live": semaphore_dns_live,
            "semaphore_dns_writes": semaphore_dns_writes,
            "semaphore_route53_admin_missing": semaphore_route53_admin_missing,
            "semaphore_route53_held_key": semaphore_route53_held_key,
            "semaphore_route53_policy": semaphore_route53_policy,
            "semaphore_route53_record": semaphore_route53_record,
        }
