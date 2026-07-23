"""Verify that every role declaring `required_by` in its
`meta/services.yml` actually ran in an Ansible run log.

A role's `meta/services.yml` MAY contain (per-service-entity):

    <entity>:
      required_by:
        categories: [web, web.app, ...]   # category handles (cf. roles/categories.yml)
        roles: [web-app-yourls, ...]      # full role names incl. category prefix

A `required_by` block MAY instead nest `compose:` / `swarm:` sub-blocks to
scope the requirement to one deploy mode (a flat block applies in every mode);
the deploy mode is inferred from the role set (swarm pulls in svc-swarm-node):

    <entity>:
      required_by:
        compose: { categories: [web] }    # required only in compose deploys

Semantics: when the current deploy contains any role whose id matches a
listed `roles` entry, OR whose category set (top-level + first sub-level)
intersects the listed `categories`, the role owning the services.yml entry
MUST have executed (at least one of its TASK blocks must end with a
non-skip status) in the run log slice that this verifier scans.

A missing event indicates a coverage regression in the deploy chain
(typically: a once-flag swallowed an include before the role could run).

CLI: `python -m cli.meta.roles.services.called --help`
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# Status indicators that prove a task block was NOT skipped. We anchor to
# line start (after optional indent) so substring matches in arbitrary
# task output cannot trigger a false positive.
_NON_SKIP_RE = re.compile(
    r"^\s*(?:ok|changed|fatal|included):\s+",
    re.MULTILINE,
)
# Ansible's log_path file (ANSIBLE_LOG_PATH, what the swarm/compose deploy feeds
# this verifier) prefixes every line with "<ts> p=<pid> u=<user> n=<name> <LVL>| ".
# Unstripped, that prefix defeats both the line-anchored _NON_SKIP_RE and the
# "\nTASK [" block split below (the TASK header no longer follows the newline),
# so every required role false-positives as "did not execute".
_LOG_PREFIX_RE = re.compile(
    r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+ p=\d+ u=\S+ n=\S+ \w+\| ",
    re.MULTILINE,
)


def categories_of(role_id: str) -> set[str]:
    """Top-level + first-sub-level categories for the given role id.

    Examples:
        web-app-yourls   -> {"web", "web-app"}
        svc-db-postgres  -> {"svc", "svc-db"}
        sys-ctl-hlth-csp -> {"sys", "sys-ctl"}
    """
    parts = role_id.split("-")
    if not parts or not parts[0]:
        return set()
    out: set[str] = {parts[0]}
    if len(parts) >= 2 and parts[1]:
        out.add(f"{parts[0]}-{parts[1]}")
    return out


_SWARM_MARKER_ROLES = frozenset({"svc-swarm-node", "svc-swarm-manager"})


def _deploy_mode(deployed_role_ids: list[str]) -> str:
    # No DEPLOYMENT_MODE in scope post-deploy: infer it from the role set, since a
    # swarm deploy always pulls in the swarm-node/manager infra and compose never does.
    return "swarm" if _SWARM_MARKER_ROLES.intersection(deployed_role_ids) else "compose"


def required_role_ids(
    *,
    roles_dir: Path,
    deployed_role_ids: list[str],
) -> set[str]:
    """Return role ids whose `required_by` matches the current deploy."""
    deployed_categories: set[str] = set()
    for d in deployed_role_ids:
        deployed_categories.update(categories_of(d))
    deployed_set = set(deployed_role_ids)
    deploy_mode = _deploy_mode(deployed_role_ids)

    required: set[str] = set()
    if not roles_dir.is_dir():
        return required
    for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
        services_yml = role_dir / ROLE_FILE_META_SERVICES
        if not services_yml.is_file():
            continue
        try:
            data = load_yaml_any(str(services_yml), default_if_missing={})
        except Exception as exc:
            print(
                f"WARN: failed to parse {services_yml}: {exc}",
                file=sys.stderr,
            )
            continue
        if not isinstance(data, dict):
            continue
        role_id = role_dir.name
        for entry in data.values():
            if not isinstance(entry, dict):
                continue
            rb = entry.get("required_by")
            if not isinstance(rb, dict):
                continue
            # required_by may scope to a deploy mode via 'compose'/'swarm' sub-keys;
            # a flat {categories, roles} applies in every mode.
            if "compose" in rb or "swarm" in rb:
                rb = rb.get(deploy_mode) or {}
                if not isinstance(rb, dict):
                    continue
            rb_categories = set(rb.get("categories") or [])
            rb_roles = set(rb.get("roles") or [])
            if (rb_categories & deployed_categories) or (rb_roles & deployed_set):
                required.add(role_id)
                break

    return required


def container_log_size(*, container: str, log_path: str) -> int:
    """Return the byte size of `log_path` inside `container`, or 0 if absent."""
    cmd = [
        "docker",
        "exec",
        container,
        "sh",
        "-c",
        f"test -f {shlex.quote(log_path)} && wc -c < {shlex.quote(log_path)} || echo 0",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        return 0
    try:
        return int((r.stdout or "0").strip() or "0")
    except ValueError:
        return 0


def _container_log_slice(
    *, container: str, log_path: str, byte_offset: int
) -> str | None:
    """Return log content from `byte_offset` to end (inside `container`).
    Returns None when the log file is missing."""
    if (
        subprocess.run(
            ["docker", "exec", container, "test", "-f", log_path],
            check=False,
        ).returncode
        != 0
    ):
        return None
    cmd = [
        "docker",
        "exec",
        container,
        "tail",
        "-c",
        f"+{max(byte_offset, 0) + 1}",
        log_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return r.stdout or ""


def _host_log_slice(*, log_path: str, byte_offset: int) -> str | None:
    """Return log content from `byte_offset` to end (host-side log file).
    Returns None when the log file is missing."""
    p = Path(log_path)
    if not p.is_file():
        return None
    try:
        with p.open("rb") as f:
            f.seek(max(byte_offset, 0))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return None


def _role_body_executed(log_content: str, role_id: str) -> bool:
    """True iff at least one `TASK [<role_id> : …]` block in `log_content`
    ends with a non-skip status (`ok:` / `changed:` / `fatal:` / `included:`).

    A skipped role still emits its wrapper TASK header followed by a
    `skipping:` status line, so a header alone is insufficient evidence
    that the role's body ran — we must see at least one non-skip outcome.
    """
    clean = _LOG_PREFIX_RE.sub("", _ANSI_RE.sub("", log_content))
    marker = f"TASK [{role_id} :"
    pos = 0
    while True:
        start = clean.find(marker, pos)
        if start < 0:
            return False
        end = clean.find("\nTASK [", start + len(marker))
        block = clean[start : end if end >= 0 else len(clean)]
        if _NON_SKIP_RE.search(block):
            return True
        pos = start + len(marker)


def verify(
    *,
    roles_dir: Path,
    log_path: str,
    deployed_role_ids: list[str],
    container: str | None = None,
    log_byte_offset: int = 0,
) -> tuple[bool, list[str]]:
    """Returns (ok, missing_role_ids).

    When `container` is given, `log_path` is interpreted as a path INSIDE
    that container and read via `docker exec tail`. When `container` is
    None, `log_path` is read directly from the host filesystem.

    Reads from `log_byte_offset` to end and asserts that every required
    role's body actually executed in that slice (i.e. at least one TASK
    block for the role ended with a non-skip status).
    """
    required = required_role_ids(
        roles_dir=roles_dir, deployed_role_ids=deployed_role_ids
    )
    if not required:
        return True, []

    if container:
        log_content = _container_log_slice(
            container=container, log_path=log_path, byte_offset=log_byte_offset
        )
    else:
        log_content = _host_log_slice(log_path=log_path, byte_offset=log_byte_offset)
    if log_content is None:
        # Missing log == we cannot prove coverage either way; treat as
        # missing for every required role so the operator notices.
        return False, sorted(required)

    missing = [
        role_id
        for role_id in sorted(required)
        if not _role_body_executed(log_content, role_id)
    ]

    return len(missing) == 0, missing
