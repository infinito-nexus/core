from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import dump_yaml_str, load_yaml_str
from utils.handler.vault import VaultScalar

APPLICATIONS_KEY = "applications"
USERS_KEY = "users"
USER_CREDENTIAL = "password"
SECRETS_KEY = "secrets"
CREDENTIALS_KEY = "credentials"
CONNECTION_PREFIX = "ansible_"
REFERENCE_KEY = "openbao"


def _load_mapping(text: str, what: str) -> Mapping:
    loaded = load_yaml_str(text)
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise AnsibleFilterError(f"{what} is no YAML mapping")
    return loaded


def _without_credentials(application_id: str, config: Any) -> Any:
    if not isinstance(config, Mapping) or SECRETS_KEY not in config:
        return config
    secrets = config[SECRETS_KEY]
    if not isinstance(secrets, Mapping) or set(secrets) - {CREDENTIALS_KEY}:
        raise AnsibleFilterError(
            f"applications.{application_id}.{SECRETS_KEY} holds more than {CREDENTIALS_KEY}, which the fixture cannot reference"
        )
    return {key: value for key, value in config.items() if key != SECRETS_KEY}


def _without_password(user: Any) -> Any:
    if not isinstance(user, Mapping):
        return user
    return {key: value for key, value in user.items() if key != USER_CREDENTIAL}


def _merge(base: Any, overlay: Any) -> Any:
    if not isinstance(base, Mapping) or not isinstance(overlay, Mapping):
        return overlay
    merged = dict(base)
    for key, value in overlay.items():
        merged[key] = _merge(base[key], value) if key in base else value
    return merged


def _is_reference(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {REFERENCE_KEY}
        and isinstance(value[REFERENCE_KEY], str)
    )


def _leaves(node: Any, path: str) -> list[tuple[str, Any]]:
    if _is_reference(node) or not isinstance(node, Mapping):
        return [(path, node)]
    return [
        leaf for key, value in node.items() for leaf in _leaves(value, f"{path}.{key}")
    ]


def _value_findings(built: Mapping) -> list[str]:
    findings = []
    for application_id, config in (built.get(APPLICATIONS_KEY) or {}).items():
        credentials = ((config or {}).get(SECRETS_KEY) or {}).get(CREDENTIALS_KEY) or {}
        prefix = f"applications.{application_id}.{SECRETS_KEY}.{CREDENTIALS_KEY}"
        findings += [
            path
            for path, value in _leaves(credentials, prefix)
            if not _is_reference(value)
        ]
    for name, user in (built.get(USERS_KEY) or {}).items():
        if (
            isinstance(user, Mapping)
            and USER_CREDENTIAL in user
            and not _is_reference(user[USER_CREDENTIAL])
        ):
            findings.append(f"users.{name}.{USER_CREDENTIAL}")
    return findings


def _vaulted(node: Any, path: str) -> list[str]:
    if isinstance(node, VaultScalar):
        return [path]
    if isinstance(node, Mapping):
        return [
            found
            for key, value in node.items()
            for found in _vaulted(value, f"{path}.{key}" if path else str(key))
        ]
    if isinstance(node, list):
        return [
            found
            for index, value in enumerate(node)
            for found in _vaulted(value, f"{path}[{index}]")
        ]
    return []


def semaphore_fixture_host_vars(
    text: str, references: Mapping[str, Any], connection: Mapping[str, Any]
) -> str:
    """Args:
    text: the host_vars file of the platform host, as its inventory holds it.
    references: the OpenBao references of the platform credentials, shaped
        ``{users: {<name>: {password: ref}}, applications: {<id>: {secrets:
        {credentials: {<field>: ref}}}}}``.
    connection: the ``ansible_*`` variables the runner reaches that host with.

    Returns:
        The host_vars of the platform host in the fixture as YAML: the
        platform's own variables without any credential value or ``ansible_*``
        variable, overlaid with ``references`` and ``connection``. A vaulted
        value or a credential that is no reference is refused, naming its path.
    """
    loaded = _load_mapping(text, "the host_vars of the platform host")
    built: dict[str, Any] = {}
    for key, value in loaded.items():
        if str(key).startswith(CONNECTION_PREFIX):
            continue
        if key == APPLICATIONS_KEY and isinstance(value, Mapping):
            built[key] = {
                app: _without_credentials(str(app), config)
                for app, config in value.items()
            }
        elif key == USERS_KEY and isinstance(value, Mapping):
            built[key] = {name: _without_password(user) for name, user in value.items()}
        else:
            built[key] = value
    built = _merge(built, references)
    built.update(connection)
    refused = sorted(_vaulted(built, "") + _value_findings(built))
    if refused:
        raise AnsibleFilterError(
            "the fixture host_vars of the platform host keep values that are no OpenBao reference: "
            + ", ".join(refused)
        )
    return dump_yaml_str(built)


def _hosts(inventory: Mapping) -> set[str]:
    found: set[str] = set()
    pending = [inventory.get("all") or {}]
    while pending:
        group = pending.pop()
        if not isinstance(group, Mapping):
            continue
        found.update(str(name) for name in (group.get("hosts") or {}))
        pending.extend((group.get("children") or {}).values())
    return found


def semaphore_fixture_workspaces(text: str, platform_hostname: str, host: str) -> str:
    """Args:
    text: the inventory file of the platform deploy.
    platform_hostname: the name that inventory gives the platform host.
    host: the name the fixture's Workspaces inventory gives it.

    Returns:
        The Workspaces inventory as YAML: ``host`` alone, in every group the
        platform inventory puts ``platform_hostname`` in.
    """
    root = _load_mapping(text, "the platform inventory").get("all") or {}
    children = (root.get("children") or {}) if isinstance(root, Mapping) else {}
    groups = sorted(
        str(name)
        for name, group in children.items()
        if isinstance(group, Mapping)
        and platform_hostname in (group.get("hosts") or {})
    )
    if not groups:
        raise AnsibleFilterError(
            f"the platform inventory puts {platform_hostname} in no group"
        )
    return dump_yaml_str(
        {"all": {"children": {name: {"hosts": {host: {}}} for name in groups}}}
    )


def semaphore_fixture_inventory_findings(
    devices: str, workspaces: str, platform: str, target: str
) -> list[str]:
    """Args:
    devices: the inventory of the ``deploy`` template, as committed.
    workspaces: the inventory of the Workspaces project, as committed.
    platform: the platform host of the fixture.
    target: the customer device of the fixture.

    Returns:
        One message per way the two inventories mix their hosts, empty when
        ``devices`` lists the target and no platform host and ``workspaces``
        lists the platform host alone.
    """
    device_hosts = _hosts(_load_mapping(devices, "devices.yml"))
    workspace_hosts = _hosts(_load_mapping(workspaces, "workspaces.yml"))
    findings = []
    if platform in device_hosts:
        findings.append(
            f"devices.yml lists the platform host {platform}, so every deploy would reach it"
        )
    if target not in device_hosts:
        findings.append(f"devices.yml lists no {target}")
    if workspace_hosts != {platform}:
        findings.append(
            f"workspaces.yml lists {sorted(workspace_hosts)}, not the platform host {platform} alone"
        )
    return findings


def _blob(public: str) -> tuple[str, ...]:
    return tuple(str(public).split()[:2])


def semaphore_fixture_key_findings(
    fixture: str, others: Mapping[str, str]
) -> list[str]:
    """Args:
    fixture: the public half of the fixture key.
    others: the public halves the fixture key has to differ from, by name.

    Returns:
        One message per named key the fixture key equals.
    """
    return [
        f"the fixture key equals the {name} key"
        for name, other in sorted(others.items())
        if _blob(other) == _blob(fixture)
    ]


class FilterModule:
    def filters(self):
        return {
            "semaphore_fixture_host_vars": semaphore_fixture_host_vars,
            "semaphore_fixture_inventory_findings": semaphore_fixture_inventory_findings,
            "semaphore_fixture_key_findings": semaphore_fixture_key_findings,
            "semaphore_fixture_workspaces": semaphore_fixture_workspaces,
        }
