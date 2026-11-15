from __future__ import annotations

import importlib.util
import ipaddress
import re
import shlex

from ansible.plugins.filter.core import (
    dict_to_list_of_dict_key_value_elements,
    list_of_dict_key_value_elements_to_dict,
)
from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "svc-virt-incus"
VARS = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN), default_if_missing={})
SERVICES = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES), default_if_missing={})
INCUS = SERVICES["incus"]
NFTABLES = read_text(str(ROLE / "templates" / "nftables.conf.j2"))
TABLE = "infinito_svc_virt_incus"

_SPEC = importlib.util.spec_from_file_location(
    "incus_workspace_filters", ROLE / "filter_plugins" / "incus_workspace.py"
)
FILTERS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(FILTERS)


def environment() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters.update(FILTERS.FilterModule().filters())
    env.filters["dict2items"] = dict_to_list_of_dict_key_value_elements
    env.filters["items2dict"] = list_of_dict_key_value_elements_to_dict
    env.filters["bool"] = lambda value: str(value).lower() in ("true", "yes", "1")
    return env


def evaluate(expression: str, variables: dict) -> object:
    """Args:
        expression: a ``{{ }}`` value of the role.
        variables: the variables it reads.

    Returns:
        The value the expression computes.
    """
    inner = expression.strip()
    if inner.startswith("{{") and inner.endswith("}}"):
        inner = inner[2:-2]
    return environment().compile_expression(inner)(**variables)


def ruleset(
    template: str,
    sources: list,
    workspaces: dict | None = None,
    listen: str | None = None,
) -> str:
    """Args:
        template: the nftables template.
        sources: ``services.incus.api.allowed_sources``.
        workspaces: ``services.incus.workspaces``, the role's default when None.
        listen: ``services.incus.api.listen``, the role's default when None.

    Returns:
        The rendered ruleset.
    """
    return (
        environment()
        .from_string(template)
        .render(
            FIREWALL_TABLE=TABLE,
            INCUS_API_SOURCES=FILTERS.incus_sources(sources),
            INCUS_API_PORT=FILTERS.incus_listen_port(listen or INCUS["api"]["listen"]),
            INCUS_WORKSPACES=workspaces or INCUS["workspaces"],
            INCUS_NETWORK=INCUS["network"],
        )
    )


def _sets(text: str) -> dict[str, list]:
    sets = {}
    for name, body in re.findall(r"set (\w+) \{(.*?)\n  \}", text, re.DOTALL):
        elements = re.search(r"elements = \{(.*?)\}", body, re.DOTALL)
        sets[name] = [
            ipaddress.ip_network(item.strip())
            for item in (elements.group(1).split(",") if elements else [])
        ]
    return sets


def _chain(text: str, name: str) -> list[list[str]]:
    body = re.search(rf"chain {name} \{{(.*?)\n  \}}", text, re.DOTALL)
    if not body:
        return []
    return [
        shlex.split(line.strip())
        for line in body.group(1).splitlines()
        if line.strip() and not line.strip().startswith("type ")
    ]


def _name_matches(pattern: str, name: str) -> bool:
    return name.startswith(pattern[:-1]) if pattern.endswith("*") else name == pattern


def _matches(rule: list[str], packet: dict, sets: dict) -> bool:
    tokens = list(rule)
    verdict = tokens.pop()
    if verdict != "drop":
        raise AssertionError(f"unexpected verdict in {rule}")
    while tokens:
        head = tokens.pop(0)
        if head == "meta" and tokens[0] == "nfproto":
            if packet.get("family") != tokens[1]:
                return False
            del tokens[:2]
        elif head == "tcp" and tokens[0] == "dport":
            if packet.get("dport") != int(tokens[1]):
                return False
            del tokens[:2]
        elif head in ("ip", "ip6") and tokens[0] == "saddr" and tokens[1] == "!=":
            if packet.get("family") != ("ipv4" if head == "ip" else "ipv6"):
                return False
            source = ipaddress.ip_address(packet["saddr"])
            if any(source in network for network in sets[tokens[2].lstrip("@")]):
                return False
            del tokens[:3]
        elif head in ("iifname", "oifname"):
            if not _name_matches(tokens[0], packet.get(head[0] + "if", "")):
                return False
            del tokens[:1]
        else:
            raise AssertionError(f"the simulator does not know {head} in {rule}")
    return True


def dropped(text: str, chain: str, **packet) -> bool:
    """Args:
        text: a rendered ruleset.
        chain: ``input`` or ``forward``.
        **packet: ``family``, ``saddr`` and ``dport`` for input, ``iif`` and
            ``oif`` for forward.

    Returns:
        Whether a rule of the chain drops the packet.
    """
    sets = _sets(text)
    return any(_matches(rule, packet, sets) for rule in _chain(text, chain))
