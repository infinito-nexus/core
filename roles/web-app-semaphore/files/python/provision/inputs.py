from __future__ import annotations

import ipaddress
import json
import os
from pathlib import Path

from provision import schema

PROVIDERS = ("hetzner", "ionos", "scs", "proxmox", "incus")
DNS_FLAVORS = ("knot", "route53", "cloudflare")
DNS_ACTIONS = ("create", "remove", "unlock")
REFUSED_SUFFIXES = (".tf", ".tf.json", ".tofu", ".tofu.json")
REFUSED_NAMES = frozenset({".terraformrc", ".tofurc"})
SKIPPED_DIRECTORIES = frozenset({".git"})
WORKSPACE_VARIABLES = {
    "workspace": "WORKSPACE",
    "dns.zone": "WORKSPACE_DNS_ZONE",
    "dns.zone_id": "WORKSPACE_DNS_ZONE_ID",
}


class RefusedError(Exception):
    """Args:
    message: what the run refuses, naming the variable or the file.
    """


def required(env, name):
    """Args:
        env: the task environment.
        name: the variable.

    Returns:
        Its value; a missing or empty one raises :class:`RefusedError`.
    """
    value = env.get(name, "")
    if not value:
        raise RefusedError(f"{name} is missing")
    return value


def _checked(value, rule, name):
    try:
        schema.check(value, rule, name)
    except schema.SchemaError as error:
        raise RefusedError(str(error)) from None
    return value


def order_line(env, interface):
    """Args:
        env: the task environment.
        interface: the decoded ``interface.json``.

    Returns:
        ``(SALES_ORDER, LINE)``, each checked against ``$defs.order``.
    """
    rules = schema.definition(interface, "order")["properties"]
    return tuple(
        _checked(required(env, name), rules[name], name)
        for name in ("SALES_ORDER", "LINE")
    )


def provider_token(env, interface):
    """Args:
        env: the task environment.
        interface: the decoded ``interface.json``.

    Returns:
        ``PROVIDER_TOKEN``, checked against ``$defs.provider_token``.
    """
    rule = schema.definition(interface, "provider_token")
    return _checked(required(env, "PROVIDER_TOKEN"), rule, "PROVIDER_TOKEN")


def workspace_document(env, interface, flavor):
    """Args:
        env: the task environment ``workspace apply`` wrote.
        interface: the decoded ``interface.json``.
        flavor: the DNS flavor of the deployment.

    Returns:
        The ``workspace.json`` document, checked against ``$defs.workspace``.
    """
    document = {
        "workspace": required(env, "WORKSPACE"),
        "dns": {
            "zone": required(env, "WORKSPACE_DNS_ZONE"),
            "zone_id": env.get("WORKSPACE_DNS_ZONE_ID", ""),
        },
    }
    try:
        schema.check(document, schema.definition(interface, "workspace"))
    except schema.SchemaError as error:
        name = WORKSPACE_VARIABLES.get(error.path, error.path)
        raise RefusedError(f"{name} {error.reason}") from None
    if (flavor == "knot") != (document["dns"]["zone_id"] == ""):
        raise RefusedError(
            f"WORKSPACE_DNS_ZONE_ID must be empty under knot and set under "
            f"route53 and cloudflare; the flavor is {flavor}"
        )
    return document


def refused_files(checkout):
    """Args:
        checkout: the workspace checkout.

    Returns:
        Every path below it that OpenTofu or Terraform would read as code or
        CLI configuration, relative and sorted.
    """
    root = Path(checkout)
    found = []
    for directory, subdirectories, files in os.walk(root):
        subdirectories[:] = sorted(set(subdirectories) - SKIPPED_DIRECTORIES)
        for name in [*files, *subdirectories]:
            lowered = name.lower()
            if lowered in REFUSED_NAMES or lowered.endswith(REFUSED_SUFFIXES):
                found.append((Path(directory) / name).relative_to(root).as_posix())
    return sorted(found)


def _unique(pairs):
    keys = [key for key, _ in pairs]
    if len(set(keys)) != len(keys):
        raise RefusedError("the tfvars file repeats a key")
    return dict(pairs)


def load_tfvars(checkout, name, interface):
    """Args:
        checkout: the workspace checkout.
        name: ``<SALES_ORDER>-<LINE>``.
        interface: the decoded ``interface.json``.

    Returns:
        The values of ``provision/<name>.tfvars.json``, checked against the
        root inputs of ``interface.json``.
    """
    relative = f"provision/{name}.tfvars.json"
    root = Path(checkout).resolve()
    path = root / relative
    if path.is_symlink() or not path.is_file() or root not in path.resolve().parents:
        raise RefusedError(f"the checkout holds no regular file {relative}")
    try:
        values = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RefusedError(f"{relative} is no JSON document") from None
    _checked(values, schema.definition(interface, "inputs"), relative)
    if values["name"] != name:
        raise RefusedError(f"{relative}: name is {values['name']!r}, not {name!r}")
    return values


def load_catalogs(directory, interface):
    """Args:
        directory: the read-only catalog mount of the provision runner.
        interface: the decoded ``interface.json``.

    Returns:
        ``{provider: catalog}``, each checked against ``$defs.catalog``.
    """
    catalogs = {}
    rule = schema.definition(interface, "catalog")
    for provider in PROVIDERS:
        path = Path(directory) / f"{provider}.json"
        if not path.is_file():
            raise RefusedError(f"the catalog mount holds no {path.name}")
        try:
            catalog = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            raise RefusedError(f"the catalog {path.name} is no JSON document") from None
        catalogs[provider] = _checked(catalog, rule, provider)
    return catalogs


def select_provider(catalogs, values):
    """Args:
        catalogs: the result of :func:`load_catalogs`.
        values: the checked tfvars.

    Returns:
        The one provider whose catalog offers the region for the flavor,
        after checking that it offers the size too.
    """
    flavor, region, size = values["flavor"], values["region"], values["size"]
    offering = [
        provider
        for provider in PROVIDERS
        if region in catalogs[provider].get(flavor, {}).get("regions", {})
    ]
    if not offering:
        empty = [provider for provider in PROVIDERS if not catalogs[provider]]
        listed = f"; empty catalogs: {', '.join(empty)}" if empty else ""
        raise RefusedError(f"no catalog offers region {region!r} for {flavor}{listed}")
    if len(offering) > 1:
        raise RefusedError(f"region {region!r} is offered by {', '.join(offering)}")
    provider = offering[0]
    if size not in catalogs[provider][flavor]["sizes"]:
        raise RefusedError(
            f"the {provider} catalog offers no size {size!r} for {flavor}"
        )
    return provider


def provision_record(document):
    """Args:
        document: the bytes of the line's ``.provision.json`` record.

    Returns:
        The record, whose ``provider`` is one of :data:`PROVIDERS`.
    """
    try:
        record = json.loads(document)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RefusedError("the provision record is no JSON document") from None
    if not isinstance(record, dict) or record.get("provider") not in PROVIDERS:
        raise RefusedError(
            f"the provision record names no provider of {', '.join(PROVIDERS)}"
        )
    return record


def recorded_provider(document, values, interface):
    """Args:
        document: the bytes of the line's ``.provision.json`` record.
        values: the checked tfvars.
        interface: the decoded ``interface.json``.

    Returns:
        ``(provider, catalog)`` the line was provisioned with, the catalog
        checked against ``$defs.catalog`` and offering the line's region.
    """
    record = provision_record(document)
    provider = record["provider"]
    rule = schema.definition(interface, "catalog")
    catalog = _checked(record.get("catalog"), rule, f"the {provider} record catalog")
    flavor, region = values["flavor"], values["region"]
    if region not in catalog.get(flavor, {}).get("regions", {}):
        raise RefusedError(
            f"the {provider} record catalog offers no region {region!r} for {flavor}"
        )
    return provider, catalog


def address(value, name):
    """Args:
        value: an IPv4 or IPv6 address.
        name: the variable it came from.

    Returns:
        The address in its canonical form.
    """
    try:
        parsed = ipaddress.ip_address(value)
    except ValueError:
        parsed = None
    if parsed is None or "%" in value:
        raise RefusedError(f"{name} {value!r} is no IPv4 or IPv6 address")
    return str(parsed)


def record_target(value, interface):
    """Args:
        value: ``HOST``, an IPv4 or IPv6 address or a fully qualified host name.
        interface: the decoded ``interface.json``.

    Returns:
        ``(address, name)``: the canonical address and an empty name, or an
        empty address and the name checked against ``$defs.host_name``.
    """
    try:
        return address(value, "HOST"), ""
    except RefusedError:
        rule = schema.definition(interface, "host_name")
        return "", _checked(value, rule, "HOST")


def target_hosts(text):
    """Args:
        text: ``WORKSPACE_TARGETS``, comma-separated ``<host>:<port>`` pairs.

    Returns:
        The hosts of the pairs, addresses in their canonical form.
    """
    hosts = set()
    for pair in filter(None, (item.strip() for item in text.split(","))):
        host, _, port = pair.rpartition(":")
        host = host.removeprefix("[").removesuffix("]")
        if not host or not port.isdigit() or not 0 < int(port) < 65536:
            raise RefusedError(f"WORKSPACE_TARGETS holds the malformed pair {pair!r}")
        try:
            hosts.add(str(ipaddress.ip_address(host)))
        except ValueError:
            hosts.add(host)
    return hosts


def dns_request(env, interface):
    """Args:
        env: the task environment.
        interface: the decoded ``interface.json``.

    Returns:
        ``{"action", "sales_order", "line", "dns_label", "host", "cname"}``;
        ``host`` holds an address and ``cname`` a host name, at most one of
        them set, and all three are empty for ``remove`` and ``unlock``.
    """
    action = env.get("DNS_ACTION", "")
    if action not in DNS_ACTIONS:
        raise RefusedError(
            f"DNS_ACTION {action!r} is not one of {', '.join(DNS_ACTIONS)}"
        )
    sales_order, line = order_line(env, interface)
    request = {
        "action": action,
        "sales_order": sales_order,
        "line": line,
        "dns_label": "",
        "host": "",
        "cname": "",
    }
    if action != "create":
        return request
    label_rule = schema.definition(interface, "inputs")["properties"]["dns_label"]
    request["dns_label"] = _checked(required(env, "DNS_LABEL"), label_rule, "DNS_LABEL")
    request["host"], request["cname"] = record_target(required(env, "HOST"), interface)
    target = request["host"] or request["cname"]
    if target not in target_hosts(env.get("WORKSPACE_TARGETS", "")):
        raise RefusedError(
            f"HOST {target} is not the host of a pair in WORKSPACE_TARGETS"
        )
    return request
