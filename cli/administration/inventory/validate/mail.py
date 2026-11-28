from __future__ import annotations

from pathlib import Path

from cli.administration.inventory.provision.services.disabler import (
    DISABLED_SERVICES_RECORD,
)
from utils.mail.provider import MAIL_SERVICE_KEY, MAIL_WRAPPER, provider_roles

from .loaders import load_yaml_file


def group_hosts(inv_dir) -> dict[str, set[str]]:
    """Hosts per inventory group.

    Args:
        inv_dir: the inventory directory; its top-level ``*.yml`` files are read.

    Returns:
        Every ``all.children.<group>.hosts`` key, merged across files.
    """
    groups: dict[str, set[str]] = {}
    for path in sorted(Path(inv_dir).glob("*.yml")):
        data = load_yaml_file(path)
        children = (
            (data.get("all") or {}).get("children") if isinstance(data, dict) else None
        )
        if not isinstance(children, dict):
            continue
        for group, node in children.items():
            hosts = node.get("hosts") if isinstance(node, dict) else None
            groups.setdefault(str(group), set()).update(
                str(host) for host in (hosts if isinstance(hosts, dict) else {})
            )
    return groups


def _disabled_wrapper(inv_dir, host: str) -> bool:
    root = Path(inv_dir) / "host_vars"
    for path in [root / f"{host}.yml", *sorted((root / host).rglob("*.yml"))]:
        data = load_yaml_file(path) if path.is_file() else None
        record = data.get(DISABLED_SERVICES_RECORD) if isinstance(data, dict) else None
        if isinstance(record, list) and MAIL_SERVICE_KEY in record:
            return True
    return False


def validate_mail_wrapper(inv_dir, providers: list[str]) -> list[str]:
    """Report hosts that carry a mail provider without the mail wrapper.

    Args:
        inv_dir: the inventory directory.
        providers: the mail provider roles, see :func:`provider_roles`.

    Returns:
        One message per provider group whose hosts are missing from the
        ``web-app-email`` group, unless their ``disable`` record names ``email``.
    """
    groups = group_hosts(inv_dir)
    wrapped = groups.get(MAIL_WRAPPER, set())
    errs: list[str] = []
    for provider in providers:
        missing = sorted(
            host
            for host in groups.get(provider, set()) - wrapped
            if not _disabled_wrapper(inv_dir, host)
        )
        if missing:
            errs.append(
                f"{inv_dir}: '{provider}' is deployed on {', '.join(missing)} "
                f"without '{MAIL_WRAPPER}', so every mail consumer stays off; "
                f"add {MAIL_WRAPPER} to the same hosts"
            )
    return errs


def validate_mail_wrapper_for_roles(inv_dir, roles_dir) -> list[str]:
    """:func:`validate_mail_wrapper` over the providers the roles tree declares.

    Args:
        inv_dir: the inventory directory.
        roles_dir: the repository ``roles/`` directory.

    Returns:
        The findings of :func:`validate_mail_wrapper`; none for a roles tree
        without the ``web-app-email`` role.
    """
    if not (Path(roles_dir) / MAIL_WRAPPER).is_dir():
        return []
    return validate_mail_wrapper(inv_dir, provider_roles(Path(roles_dir)))
