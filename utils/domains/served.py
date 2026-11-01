"""Hosts an application serves below a parent for the members of an RBAC role.

Declared next to ``canonical`` in the application's ``domains``::

    served:
      - parent: user.blog.{{ DOMAIN_PRIMARY }}
        role: site-owner
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from utils.roles.rbac.scoped import members_with_role

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

SERVED_KEY = "served"
SERVED_FACT = "CURRENT_PLAY_SERVED_DOMAINS"
WILDCARD_PREFIX = "*."
MEMBER_LABEL = re.compile(r"[a-z1-9]+|[a-z1-9]{4}0[a-z1-9]+")
MEMBER_LABEL_MAX = 63
ILLEGAL_LABELS = frozenset(
    {"www", "web", "root", "admin", "main", "invite", "administrator", "files", "blog"}
)


def is_member_label(username: str) -> bool:
    """Tell whether a username can name a member host.

    Args:
        username: the login exactly as the inventory or Keycloak holds it.

    Returns:
        True for a Keycloak username (``[a-z1-9]`` or the agent form
        ``<4 chars>0<suffix>``) that fits a DNS label and is no WordPress
        ``illegal_names`` entry.
    """
    return (
        len(username) <= MEMBER_LABEL_MAX
        and MEMBER_LABEL.fullmatch(username) is not None
        and username not in ILLEGAL_LABELS
    )


def served_specs(
    application_id: str, app_cfg: Mapping[str, Any]
) -> tuple[list[tuple[str, str]], list[str]]:
    """Return the served declarations of one application.

    Args:
        application_id: the application, for problem messages.
        app_cfg: its rendered configuration.

    Returns:
        ``(parent, role)`` per valid entry of ``domains.served`` in declaration
        order, and one message per entry that is not exactly a rendered
        ``parent`` and a ``role``.
    """
    domains = app_cfg.get("domains")
    if not isinstance(domains, dict) or SERVED_KEY not in domains:
        return [], []
    entries = domains[SERVED_KEY]
    if not isinstance(entries, list):
        return [], [f"{application_id}.domains.{SERVED_KEY} must be a list"]
    specs = []
    problems = []
    for index, entry in enumerate(entries):
        where = f"{application_id}.domains.{SERVED_KEY}[{index}]"
        if not isinstance(entry, dict) or set(entry) != {"parent", "role"}:
            problems.append(f"{where} must map exactly 'parent' and 'role'")
            continue
        parent = str(entry["parent"]).strip().lower()
        role = str(entry["role"]).strip()
        if not parent or not role or "{{" in parent or "{%" in parent:
            problems.append(f"{where} needs a rendered parent domain and a role")
            continue
        specs.append((parent, role))
    return specs, problems


def declares_served(
    applications: Mapping[str, Any], application_ids: Iterable[str]
) -> bool:
    """Tell whether any of the given applications declares ``domains.served``.

    Args:
        applications: the merged applications.
        application_ids: the applications to check.
    """
    return any(
        isinstance(domains, dict) and SERVED_KEY in domains
        for domains in (
            (applications.get(application_id) or {}).get("domains")
            for application_id in application_ids
        )
    )


def served_domains(
    applications: Mapping[str, Any],
    users: Mapping[str, Any],
    application_ids: Iterable[str],
    *,
    wildcard_certificate: Callable[[Mapping[str, Any]], bool],
    known_domains: Iterable[str],
) -> dict[str, list[Any]]:
    """Return the vhost names the given applications serve for role members.

    Args:
        applications: the merged, rendered applications.
        users: the merged users mapping.
        application_ids: the applications to resolve; ids without a
            configuration are skipped.
        wildcard_certificate: tells for one application configuration whether
            a wildcard name of it gets a certificate.
        known_domains: every domain, redirect source and ``www.`` variant of
            the host; no served name may repeat one.

    Returns:
        ``entries``: ``{"name", "application_id", "members", "hosts"}`` per
        served vhost name. With a wildcard certificate one ``*.<parent>`` per
        declaration serves all its members; without one every member host is
        a name of its own. ``problems``: one message per declaration error,
        member whose username names no host, or name that repeats a known
        one; such members and names are left out of ``entries``.
    """
    taken = {str(domain).lower() for domain in known_domains}
    entries: list[dict[str, Any]] = []
    problems: list[str] = []
    for application_id in sorted(set(application_ids)):
        app_cfg = applications.get(application_id)
        if not isinstance(app_cfg, dict):
            continue
        specs, spec_problems = served_specs(application_id, app_cfg)
        problems.extend(spec_problems)
        for parent, role in specs:
            members = []
            for username in members_with_role(users, application_id, role):
                if is_member_label(username):
                    members.append(username)
                else:
                    problems.append(
                        f"{application_id}: {role} member '{username}' names no "
                        f"host below {parent}"
                    )
            if wildcard_certificate(app_cfg):
                named = [(WILDCARD_PREFIX + parent, members)]
            else:
                named = [(f"{member}.{parent}", [member]) for member in members]
            for name, served in named:
                if name in taken:
                    problems.append(
                        f"{application_id}: served name '{name}' repeats a domain "
                        "of this host"
                    )
                    continue
                taken.add(name)
                entries.append(
                    {
                        "name": name,
                        "application_id": application_id,
                        "members": served,
                        "hosts": [f"{member}.{parent}" for member in served],
                    }
                )
    return {"entries": entries, "problems": problems}


def served_owners(variables: Mapping[str, Any]) -> dict[str, str]:
    """Return ``{served name: application id}`` from ``CURRENT_PLAY_SERVED_DOMAINS``.

    Args:
        variables: host variables; empty until the constructor has set the fact.
    """
    return {
        str(entry["name"]).lower(): str(entry["application_id"])
        for entry in variables.get(SERVED_FACT) or []
    }
