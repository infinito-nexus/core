"""Where a repository file sits relative to a deploy: the location rules the
classifier and the symbol index share.

A file is either a role's own (it changes that role), a test (it runs in T0),
a plugin (it changes whoever calls it by name), a group_vars file (it changes
whoever reads one of its keys), a module others import, deploy machinery or a
global deploy file (it changes every deploy), CI or developer tooling no
deploy runs, or unknown. The tooling list is closed on purpose: a script
directory nobody listed counts as deploy machinery, so a new one widens the
plan instead of silently narrowing it. ``agents/`` is not tooling: the agent
roles read its YAML through the ``agent_config`` lookup at deploy time.
"""

from __future__ import annotations

from typing import NamedTuple

ROLE = "role"
TEST = "test"
DOCS = "docs"
GROUP_VARS = "group_vars"
PLUGIN = "plugin"
MODULE = "module"
WORKFLOW = "workflow"
GLOBAL = "global"
TOOLING = "tooling"
UNKNOWN = "unknown"

DOC_SUFFIXES = (".md", ".rst")
YAML_SUFFIXES = (".yml", ".yaml")
ROLE_PLUGIN_DIRS = {
    "filter_plugins": "filter",
    "lookup_plugins": "lookup",
    "action_plugins": "action",
    "library": "module",
}
SHARED_PLUGIN_DIRS = {
    "plugins/filter/": "filter",
    "plugins/lookup/": "lookup",
    "plugins/action/": "action",
    "library/": "module",
}
DEPLOY_MACHINERY = (
    "cli/administration/",
    "cli/core/",
    "cli/meta/env/",
)
GLOBAL_DEPLOY = (
    "tasks/",
    "templates/",
    "playbooks/",
    "inventories/",
    "compose/",
    "playbook.yml",
    "playbook-sync.yml",
    "compose.yml",
    "Dockerfile",
    "ansible.cfg",
)
WORKFLOWS = (".github/workflows/", ".github/actions/")
TOOLING_PATHS = (
    "cli/",
    "scripts/agents/",
    "scripts/ci/",
    "scripts/git/",
    "scripts/github/",
    "scripts/i18n/",
    "scripts/legal/",
    "scripts/lint/",
    "scripts/make/",
    "scripts/tests/unit/",
)


class Place(NamedTuple):
    """Where one path sits.

    Attributes:
        kind: one of the kind constants of this module.
        role: the role a role path belongs to, else empty.
        rest: the path below ``roles/<role>/`` for a role path, else empty.
        plugin: the plugin type (filter, lookup, action, module) of a plugin
            file, else empty.
    """

    kind: str
    role: str = ""
    rest: str = ""
    plugin: str = ""


def _plugin_type(path: str, rest: str) -> str:
    if not path.endswith(".py") or path.endswith("/__init__.py"):
        return ""
    if rest:
        head, _, tail = rest.partition("/")
        return ROLE_PLUGIN_DIRS.get(head, "") if tail and "/" not in tail else ""
    for prefix, kind in SHARED_PLUGIN_DIRS.items():
        if path.startswith(prefix):
            return kind
    return ""


def place(path: str) -> Place:
    """Return where *path* sits.

    Args:
        path: repository-relative POSIX path.
    """
    parts = path.split("/", 2)
    if parts[0] == "roles":
        if len(parts) < 3 or not parts[1] or not parts[2]:
            return Place(UNKNOWN)
        plugin = _plugin_type(path, parts[2])
        return Place(PLUGIN if plugin else ROLE, parts[1], parts[2], plugin)
    if path.startswith("tests/"):
        return Place(TEST)
    if path.endswith(DOC_SUFFIXES):
        return Place(DOCS)
    if path.startswith("group_vars/") and path.endswith(YAML_SUFFIXES):
        return Place(GROUP_VARS)
    if path.startswith(WORKFLOWS):
        return Place(WORKFLOW)
    plugin = _plugin_type(path, "")
    if plugin:
        return Place(PLUGIN, plugin=plugin)
    if path.startswith(DEPLOY_MACHINERY + GLOBAL_DEPLOY):
        return Place(GLOBAL)
    if path.startswith(TOOLING_PATHS):
        return Place(TOOLING)
    if path.startswith("scripts/"):
        return Place(GLOBAL)
    if path.endswith(".py"):
        return Place(MODULE)
    return Place(UNKNOWN)
