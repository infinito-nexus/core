from __future__ import annotations

import ipaddress
import json
import re
from importlib.util import module_from_spec, spec_from_file_location

from monitoring import PROJECT_ROOT

SCRIPT = "monitoring.py"
SHARE_SCHEMA = PROJECT_ROOT / "utils" / "platform_monitoring.py"
_SHARE_SPEC = spec_from_file_location("platform_monitoring", SHARE_SCHEMA)
SHARE = module_from_spec(_SHARE_SPEC)
_SHARE_SPEC.loader.exec_module(SHARE)
checkmk_host_name = SHARE.checkmk_host_name
path_host = SHARE.host_segment
WORKSPACE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
HOSTNAME = re.compile(rf"(?=.{{1,253}}$){LABEL}(?:\.{LABEL})*")
DOMAIN = re.compile(
    r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}"
)
DAYS = re.compile(r"[1-9][0-9]{0,3}")
COMMIT = re.compile(r"[0-9a-f]{40}")
DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
ALIAS_PREFIX = "ws-"
ACTIONS = ("apply", "remove")
APPLY_ONLY = ("INVENTORY_COMMIT", "DNS_LABEL")
SETTINGS = (
    "MONITOR_CHECKMK_API",
    "MONITOR_CHECKMK_SITE",
    "MONITOR_CACERT",
    "MONITOR_TLS_WARN_DAYS",
    "MONITOR_TLS_CRIT_DAYS",
    "MONITOR_PROMETHEUS_DIR",
    "MONITOR_PROMETHEUS_RELOAD_URL",
    "WORKSPACE_PRIVATE_TARGETS",
)
SHELL_SETTINGS = (
    "SEMAPHORE_JWT",
    "MONITOR_INVENTORY_REPOSITORY",
    "MONITOR_INVENTORY_FILE",
    "DEPLOY_VAULT_PASSWORD",
    "DEPLOY_LOGIN",
    "SSH_AUTH_SOCK",
    "WORKSPACE_INVENTORY_FILE",
    "BAO_ADDR",
    "BAO_CACERT",
    "BAO_MONITORING_ROLE",
    "BAO_TOKEN_FILE",
    "INFINITO_SRC_DIR",
)
PRESENT_SETTINGS = ("DEPLOY_KNOWN_HOSTS",)


class RefusalError(Exception):
    pass


class RunError(Exception):
    pass


def refusal_line(workspace, reason):
    """Args:
    workspace: the WORKSPACE value as the task got it, None when unset.
    reason: why the task refuses.

    Returns:
        The last line of a refused run, GUI 062 Decision 28 format.
    """
    return json.dumps({"workspace": workspace, "refused": reason})


def matches(pattern, value):
    """Args:
    pattern: a compiled pattern.
    value: the value to check.

    Returns:
        Whether ``value`` is a one-line string the whole of which ``pattern``
        matches.
    """
    return isinstance(value, str) and "\n" not in value and pattern.fullmatch(value)


def checked_hostname(value, what):
    if not matches(HOSTNAME, value):
        raise RefusalError(f"{what} is no hostname")
    return value


def checked_domain(value, what):
    if not matches(DOMAIN, value):
        raise RefusalError(f"{what} is no lowercase domain")
    return value


def checked_address(value, what):
    if isinstance(value, str) and "%" in value:
        raise RefusalError(f"{what} carries an IPv6 scope id")
    if isinstance(value, str) and "\n" not in value:
        try:
            return str(ipaddress.ip_address(value))
        except ValueError:
            pass
    return checked_hostname(value, what)


def validate(env):
    """Args:
    env: the task environment.

    Returns:
        ``(workspace, action, host)``; raises :class:`RefusalError` before any
        write. WORKSPACE is the bare lowercase id, checked as
        ``workspace.py`` does; every setting of ``SETTINGS`` is required.
    """
    workspace = env.get("WORKSPACE") or ""
    action = env.get("MONITOR_ACTION") or ""
    if not matches(WORKSPACE, workspace):
        raise RefusalError("WORKSPACE is no lowercase UUID")
    if action not in ACTIONS:
        raise RefusalError(f"MONITOR_ACTION is none of {', '.join(ACTIONS)}")
    host = env.get("MONITOR_HOST")
    try:
        SHARE.canonical_host(host)
    except ValueError as error:
        raise RefusalError(f"MONITOR_HOST: {error}") from None
    if action == "apply" and not matches(COMMIT, env.get("INVENTORY_COMMIT")):
        raise RefusalError("INVENTORY_COMMIT is no 40-digit lowercase hex commit")
    if action == "apply" and not matches(DNS_LABEL, env.get("DNS_LABEL")):
        raise RefusalError("DNS_LABEL is no lowercase DNS label")
    for name in APPLY_ONLY:
        if action == "remove" and env.get(name):
            raise RefusalError(f"{name} is not taken by remove")
    settings(env)
    return workspace, action, host


def settings(env):
    """Args:
    env: the task environment.

    Returns:
        ``api``, ``site``, ``cacert`` and ``tls_days`` ``(warn, crit)``; a
        missing or malformed setting raises :class:`RefusalError` naming it.
    """
    for key in SETTINGS:
        if not env.get(key):
            raise RefusalError(f"{key} is unset")
    if not env["MONITOR_CHECKMK_API"].startswith("https://"):
        raise RefusalError("MONITOR_CHECKMK_API is no https URL")
    for key in ("MONITOR_CACERT", "MONITOR_PROMETHEUS_DIR"):
        if not env[key].startswith("/"):
            raise RefusalError(f"{key} is no absolute path")
    if not env["MONITOR_PROMETHEUS_RELOAD_URL"].startswith(("http://", "https://")):
        raise RefusalError("MONITOR_PROMETHEUS_RELOAD_URL is no http or https URL")
    days = []
    for key in ("MONITOR_TLS_WARN_DAYS", "MONITOR_TLS_CRIT_DAYS"):
        if not matches(DAYS, env[key]):
            raise RefusalError(f"{key} is no positive number of days")
        days.append(int(env[key]))
    if days[0] <= days[1]:
        raise RefusalError("MONITOR_TLS_WARN_DAYS is not above MONITOR_TLS_CRIT_DAYS")
    try:
        private = [
            ipaddress.ip_network(network, strict=False)
            for network in json.loads(env["WORKSPACE_PRIVATE_TARGETS"])
        ]
    except (TypeError, ValueError) as error:
        raise RefusalError(
            "WORKSPACE_PRIVATE_TARGETS is no JSON list of networks"
        ) from error
    return {
        "api": env["MONITOR_CHECKMK_API"],
        "site": env["MONITOR_CHECKMK_SITE"],
        "cacert": env["MONITOR_CACERT"],
        "tls_days": tuple(days),
        "private": private,
    }


def shell_settings(env):
    """Args:
    env: the environment ``monitoring.sh`` starts with.

    Raises:
        RefusalError: a setting of ``SHELL_SETTINGS`` is unset or empty, or
            one of ``PRESENT_SETTINGS`` (which may be empty) is unset.
    """
    for key in SHELL_SETTINGS:
        if not env.get(key):
            raise RefusalError(f"{key} is unset")
    for key in PRESENT_SETTINGS:
        if key not in env:
            raise RefusalError(f"{key} is unset")
