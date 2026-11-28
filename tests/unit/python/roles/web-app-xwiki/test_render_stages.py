from __future__ import annotations

import importlib.util
import itertools
import json
import os
import unittest
import warnings
from typing import TYPE_CHECKING, Any

from ansible.plugins.filter.core import FilterModule as AnsibleFilters
from ansible.plugins.test.core import TestModule as AnsibleTests
from jinja2 import (
    ChainableUndefined,
    DebugUndefined,
    Environment,
    FunctionLoader,
    StrictUndefined,
    TemplateError,
    meta,
)
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import (
    ROLE_DIR_META_ADDONS,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

ROLE = PROJECT_ROOT / "roles/web-app-xwiki"
STAGE_FILES = (ROLE / "tasks/00_core.yml", ROLE / "tasks/02_manager_ops.yml")
PROBE = ROLE / "tasks/utils/extensions_ready.yml"
PLUGIN_CHECK = "_check_extension_via_groovy.yml"
HTTP_CALL = "http.yml"
UNMODELLED_INCLUDES = ("rest_session.yml", "resolve_host_cid.yml", "netns.yml")
ROLE_VARS = ROLE / ROLE_FILE_VARS_MAIN
COMPOSE_TEMPLATE = ROLE / ROLE_FILE_TEMPL_COMPOSE
PROPERTIES_TEMPLATE = ROLE / "templates/xwiki.properties.j2"
COMPOSE_WRITER_ROLES = (ROLE, PROJECT_ROOT / "roles/sys-svc-compose")
WRITE_MODULES = (
    "stack_host_template",
    "stack_host_copy",
    "template",
    "copy",
    "ansible.builtin.template",
    "ansible.builtin.copy",
)
INSTANCE_DIR = "/opt/compose/xwiki"
CONTAINER_PATHS = {
    "directories.instance": f"{INSTANCE_DIR}/",
    "files.compose": f"{INSTANCE_DIR}/compose.yml",
}
COMPOSE_MODE = "0640"
COMPOSE_SOURCE = "compose.yml.j2"
COMPOSE_INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": 'services:\n{{ "\\n" }}\n'
}
LDAP_KEYS = {
    "XWIKI_CFG_LDAP_SERVER",
    "XWIKI_CFG_LDAP_PORT",
    "XWIKI_CFG_LDAP_BASE_DN",
    "XWIKI_CFG_LDAP_BIND_DN",
    "XWIKI_CFG_LDAP_BIND_PASS",
    "XWIKI_CFG_LDAP_FIELDS_MAPPING",
    "XWIKI_CFG_LDAP_GROUP_MAPPING",
    "XWIKI_CFG_LDAP_TRYLOCAL",
    "XWIKI_CFG_LDAP_UID_ATTR",
}
FLUSH_CONFIG = "flush_config.yml"
STACK_ROLE = "svc-stack"
STACK_ENTRY = "consumer.yml"
STACK_BACKEND_ENTRY = (
    PROJECT_ROOT / "roles/svc-stack/tasks/consumer/back.yml",
    PROJECT_ROOT / "roles/svc-stack/tasks/batch/back.yml",
)
INCLUDE_CHAIN = ("svc-stack", "sys-svc-compose")
ROLE_SCOPED_NAMES = (
    "role_name",
    "role_path",
    "ansible_role_name",
    "ansible_parent_role_names",
    "ansible_parent_role_paths",
    "ansible_collection_name",
    "item",
    "ansible_loop",
    "ansible_loop_var",
    "ansible_index_var",
)
SWITCHES = (
    "xwiki_oidc_enabled_switch",
    "xwiki_ldap_enabled_switch",
    "xwiki_blobstore_s3_enabled_switch",
)
READY = "xwiki_extensions_ready"
BLOB_S3 = "org.xwiki.commons:xwiki-commons-store-blob-s3"
HOST = "stack-host"
CORE = "18.9.0"
BLOB_VERSION = "18.9.0"

_spec = importlib.util.spec_from_file_location(
    "xwiki_filters", ROLE / "filter_plugins/xwiki_filters.py"
)
_filters = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_filters)


def to_bool(value: Any) -> bool:
    """Convert a rendered switch the way Ansible's ``bool`` filter does.

    Args:
        value: a bool or the string a Jinja expression rendered to.

    Returns:
        The boolean the role's templates see.
    """
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "on", "1")


def jinja(native: bool) -> Environment:
    """Return a strict Jinja environment carrying the filters and tests the role uses.

    Args:
        native: render Python values instead of strings when true.

    Returns:
        The environment.
    """
    env = (NativeEnvironment if native else Environment)(
        autoescape=True, undefined=StrictUndefined
    )
    env.filters.update(AnsibleFilters().filters())
    env.tests.update(AnsibleTests().tests())
    env.filters["bool"] = to_bool
    env.filters["xwiki_enabled_install_items"] = _filters.xwiki_enabled_install_items
    env.filters["xwiki_extension_status"] = _filters.xwiki_extension_status
    return env


def render(value: Any, context: dict[str, Any]) -> Any:
    """Render a task value natively, descending into mappings and lists.

    Args:
        value: a Jinja string, or a mapping or list of them.
        context: the variables in scope.

    Returns:
        The value as Ansible templates it.
    """
    if isinstance(value, dict):
        return {key: render(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [render(item, context) for item in value]
    if isinstance(value, str):
        return jinja(native=True).from_string(value).render(context)
    return value


def flatten(tasks: Any) -> list[dict[str, Any]]:
    """Return every task of a task list in the order Ansible reaches it.

    Args:
        tasks: a parsed task list whose entries may nest under
            ``block`` / ``rescue`` / ``always``.

    Returns:
        The tasks as a flat list, each parent before its children.
    """
    flat: list[dict[str, Any]] = []
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        flat.append(task)
        for key in ("block", "rescue", "always"):
            flat.extend(flatten(task.get(key)))
    return flat


def tasks_of(path: Any) -> list[dict[str, Any]]:
    """Return every task of a task file, descending into blocks.

    Args:
        path: the task file.

    Returns:
        The tasks in the order Ansible reaches them.
    """
    return flatten(load_yaml_str(read_text(str(path))))


def role_vars() -> dict[str, Any]:
    """Return the role's vars/main.yml unrendered.

    Returns:
        Each variable name mapped to its raw Jinja string.
    """
    return load_yaml_str(read_text(str(ROLE_VARS)))


def scoped(
    tasks: Any, inherited: dict[str, Any]
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Pair every task with the vars Ansible puts in its scope from enclosing blocks.

    Args:
        tasks: a parsed task list whose entries may nest under
            ``block`` / ``rescue`` / ``always``.
        inherited: the vars of the enclosing blocks.

    Returns:
        ``(task, vars)`` per task, each parent before its children.
    """
    flat: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        scope = {**inherited, **(task.get("vars") or {})}
        flat.append((task, scope))
        for key in ("block", "rescue", "always"):
            flat.extend(scoped(task.get(key), scope))
    return flat


def scoped_tasks_of(path: Any) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Return every task of a task file with its block-inherited vars.

    Args:
        path: the task file.

    Returns:
        ``(task, vars)`` in the order Ansible reaches them.
    """
    return scoped(load_yaml_str(read_text(str(path))), {})


def render_stages() -> list[dict[str, Any]]:
    """Return the vars in scope at every xwiki.properties render, in deploy order.

    Returns:
        One mapping per include of tasks/utils/flush_config.yml.
    """
    return [
        scope
        for path in STAGE_FILES
        for task, scope in scoped_tasks_of(path)
        if str(task.get("include_tasks") or "").endswith(FLUSH_CONFIG)
    ]


def switches_of(stage: dict[str, Any], flags: dict[str, bool]) -> tuple[bool, ...]:
    """Evaluate one stage's switches for one inventory.

    Args:
        stage: the ``vars`` mapping of a render.
        flags: the feature flags and the extensions_ready probe result.

    Returns:
        ``(oidc, ldap, s3)`` as the render sees them.
    """
    env = jinja(native=False)
    return tuple(
        to_bool(env.from_string(str(stage[name])).render(**flags)) for name in SWITCHES
    )


def flag_sets() -> list[dict[str, bool]]:
    """Return every feature flag combination 01_validation.yml admits.

    Returns:
        One mapping per combination of OIDC, LDAP and object store, never
        OIDC and LDAP both on, with the sso and ldap login methods at their
        lint-pinned defaults, which follow the services.
    """
    return [
        {
            "XWIKI_OIDC_ENABLED": oidc,
            "XWIKI_LDAP_ENABLED": ldap,
            "XWIKI_OBJSTORE_ENABLED": objstore,
            "XWIKI_LOGIN_SSO": oidc,
            "XWIKI_LOGIN_LDAP": ldap,
        }
        for oidc, ldap, objstore in itertools.product((False, True), repeat=3)
        if not (oidc and ldap)
    ]


def config_lookup(flags: dict[str, bool]) -> Callable[..., Any]:
    """Return a ``lookup`` stand-in answering the config reads the plugin set makes.

    Args:
        flags: the feature flags.

    Returns:
        A callable shaped like ``lookup('config', application_id, key)``.
    """
    answers: dict[str, Any] = {
        "services.sso.enabled": flags["XWIKI_OIDC_ENABLED"],
        "services.ldap.enabled": flags["XWIKI_LDAP_ENABLED"],
        "services.litellm.enabled": False,
    }

    def lookup(_kind: str, _application_id: str, key: str) -> Any:
        if key != "addons":
            return answers[key]
        return {
            path.stem: {
                **spec,
                "enabled": render(spec["enabled"], {"lookup": lookup}),
            }
            for path in sorted((ROLE / ROLE_DIR_META_ADDONS).glob("*.yml"))
            for spec in [load_yaml_str(read_text(str(path)))]
        }

    return lookup


def plugins(flags: dict[str, bool]) -> list[dict[str, Any]]:
    """Render XWIKI_PLUGINS, the add-on set the probe checks.

    Args:
        flags: the feature flags.

    Returns:
        The ``{id, version}`` entries the probe requires at their pins.
    """
    raw = role_vars()
    context: dict[str, Any] = {
        **flags,
        "application_id": "web-app-xwiki",
        "XWIKI_BLOBSTORE_EXTENSION_VERSION": BLOB_VERSION,
        "lookup": config_lookup(flags),
    }
    context["XWIKI_BLOBSTORE_EXTENSIONS"] = render(
        raw["XWIKI_BLOBSTORE_EXTENSIONS"], context
    )
    return render(raw["XWIKI_PLUGINS"], context)


def wiki_answer(
    register: str, context: dict[str, Any], installed: set[str] | None
) -> dict[str, Any]:
    """Answer one HTTP call of the probe chain as a running wiki would.

    Args:
        register: the register name of the call.
        context: the variables in scope.
        installed: extension ids installed at their pins, ``None`` when no
            wiki answers.

    Returns:
        The registered result.
    """
    if installed is None:
        return {"status": -1, "changed": False}
    ext_id = context.get("ext_id")
    found = f"INSTALLED::{ext_id}::{context.get('ext_version')}"
    return {
        "_xwiki_running": {
            "status": 200,
            "headers": {
                "xwiki-user": f"xwiki:XWiki.{context['XWIKI_SUPERADMIN_USERNAME']}"
            },
        },
        "_xwiki_running_core": {
            "status": 200,
            "content": f"<version>{context['XWIKI_CORE_VERSION']}</version>",
        },
        "_put_checker": {"status": 201},
        "_check_output": {
            "status": 200,
            "content": found if ext_id in installed else "NOT_INSTALLED",
        },
        "_delete_checker": {"status": 204},
    }[register]


def run(
    path: Path,
    facts: dict[str, Any],
    scope: dict[str, Any],
    installed: set[str] | None,
) -> None:
    """Execute a task file of the probe chain against a modelled wiki.

    Args:
        path: the task file.
        facts: host facts, updated in place by ``set_fact`` and ``register``.
        scope: include and loop variables visible to the file.
        installed: forwarded to ``wiki_answer``.
    """
    run_tasks(load_yaml_str(read_text(str(path))), path, facts, scope, installed)


def run_tasks(
    tasks: Any,
    path: Path,
    facts: dict[str, Any],
    scope: dict[str, Any],
    installed: set[str] | None,
) -> None:
    """Execute a task list of the probe chain, descending into blocks.

    Args:
        tasks: the parsed task list.
        path: the task file the list comes from, for the error message.
        facts: host facts, updated in place by ``set_fact`` and ``register``.
        scope: include, block and loop variables visible to the list.
        installed: forwarded to ``wiki_answer``; ``None`` also means no
            container or swarm service of the wiki runs.
    """
    for task in tasks or []:
        loop_var = (task.get("loop_control") or {}).get("loop_var", "item")
        items = render(task["loop"], {**facts, **scope}) if "loop" in task else [None]
        include = str(
            task.get("include_tasks") or task.get("ansible.builtin.include_tasks") or ""
        )
        for item in items:
            local = {**scope, **({loop_var: item} if "loop" in task else {})}
            when = task.get("when", [])
            conditions = when if isinstance(when, list) else [when]
            if not all(
                to_bool(render(f"{{{{ {c} }}}}", {**facts, **local}))
                for c in conditions
            ):
                if "register" in task:
                    facts[task["register"]] = {"skipped": True, "changed": False}
                continue
            if include.endswith(HTTP_CALL):
                result = task["vars"]["xwiki_http_result"]
                facts[result] = wiki_answer(result, {**facts, **local}, installed)
                continue
            if any(name in include for name in UNMODELLED_INCLUDES):
                continue
            local.update(render(task.get("vars") or {}, {**facts, **local}))
            context = {**facts, **local}
            if "block" in task:
                run_tasks(task["block"], path, facts, local, installed)
            elif "set_fact" in task:
                for key, value in task["set_fact"].items():
                    facts[str(render(key, context))] = render(value, context)
            elif include.endswith(PLUGIN_CHECK):
                run(ROLE / "tasks" / PLUGIN_CHECK, facts, local, installed)
            elif "ansible.builtin.command" in task:
                running = "" if installed is None else "xwiki-container-id"
                facts[task["register"]] = {"rc": 0, "stdout": running}
            elif "ansible.builtin.script" in task:
                facts[task["register"]] = {"rc": 1 if installed is None else 0}
            else:
                raise AssertionError(f"{path.name}: unmodelled task {task.get('name')}")


def probe(flags: dict[str, bool], installed: set[str] | None) -> bool:
    """Run tasks/utils/extensions_ready.yml on a stack host against a modelled wiki.

    Args:
        flags: the feature flags.
        installed: extension ids the running wiki carries at their pins,
            ``None`` when no wiki answers; the core always runs on its pin.

    Returns:
        The ``xwiki_extensions_ready`` fact the chain sets.
    """
    raw = role_vars()
    facts: dict[str, Any] = {
        **flags,
        "IS_STACK_HOST": True,
        "IS_SWARM_MODE": False,
        "XWIKI_SSO_ENABLED": render(raw["XWIKI_SSO_ENABLED"], flags),
        "XWIKI_SUPERADMIN_USERNAME": raw["XWIKI_SUPERADMIN_USERNAME"],
        "XWIKI_CORE_VERSION": CORE,
        "XWIKI_PLUGINS": plugins(flags),
        "inventory_hostname": HOST,
        "role_path": str(ROLE),
    }
    facts["hostvars"] = {HOST: facts}
    run(PROBE, facts, {}, installed)
    return to_bool(facts[READY])


def converged(flags: dict[str, bool]) -> set[str] | None:
    """Model a wiki carrying every add-on of XWIKI_PLUGINS on its pin.

    Args:
        flags: the feature flags.

    Returns:
        The installed extension ids.
    """
    return {plugin["id"] for plugin in plugins(flags)}


def fresh(_flags: dict[str, bool]) -> set[str] | None:
    """Model a host where no wiki answers yet.

    Args:
        _flags: the feature flags.

    Returns:
        ``None``.
    """
    return None


def without_blob_extension(flags: dict[str, bool]) -> set[str] | None:
    """Model a pinned wiki that lacks the blob-s3 store extension.

    Args:
        flags: the feature flags.

    Returns:
        Every XWIKI_PLUGINS id except the blob-s3 store.
    """
    return {plugin["id"] for plugin in plugins(flags)} - {BLOB_S3}


def inventories(
    wiki: Callable[[dict[str, bool]], set[str] | None],
) -> list[dict[str, bool]]:
    """Return every admitted flag combination with the probe result it yields.

    Args:
        wiki: maps the flags to the modelled wiki's installed extension ids.

    Returns:
        One mapping per entry of ``flag_sets()`` carrying
        ``xwiki_extensions_ready`` as the probe chain sets it.
    """
    return [{**flags, READY: probe(flags, wiki(flags))} for flags in flag_sets()]


class Placeholder(str):
    __slots__ = ()

    def __getattr__(self, name: str) -> Placeholder:
        if name.startswith("__"):
            raise AttributeError(name)
        return Placeholder(f"{self}.{name}")


def include_chain_vars() -> set[str]:
    """Return the defaults and vars of the roles svc-stack includes down to sys-svc-compose.

    Returns:
        The variable names only the 04_files render sees, without those the
        stack's backend entry binds to the consumer's own value.
    """
    names: set[str] = set()
    for role in INCLUDE_CHAIN:
        for kind in ("defaults", "vars"):
            path = PROJECT_ROOT / "roles" / role / kind / "main.yml"
            if path.exists():
                names.update(load_yaml_str(read_text(str(path))) or {})
    for entry in STACK_BACKEND_ENTRY:
        for task in load_yaml_str(read_text(str(entry))) or []:
            names.difference_update(task.get("vars") or {})
    return names


def template_action_env(lstrip_blocks: bool) -> Environment:
    """Return a Jinja environment configured as Ansible's template action renders.

    Args:
        lstrip_blocks: true for compose.yml.j2, which stack_host_template
            renders with ``lstrip_blocks``.

    Returns:
        A strict environment with ``trim_blocks`` on and no autoescaping.
    """
    env = jinja(native=False)
    env.autoescape = False
    env.trim_blocks = True
    env.lstrip_blocks = lstrip_blocks
    return env


def compose_lookup(kind: str, *args: Any, **kwargs: Any) -> Any:
    """Stand in for ``lookup`` with YAML fragments shaped like the real plugins'.

    Args:
        kind: the lookup plugin name.
        args: the lookup terms.
        kwargs: the lookup options.

    Returns:
        A ``build`` block for ``template``, an attribute-bearing placeholder for
        ``volume``, else one ``kind: "<terms>"`` mapping line.
    """
    if kind == "template":
        return "build:\n  context: ."
    if kind == "volume":
        return Placeholder(f"{kind}:{args!r}")
    return f"{kind}: {json.dumps(repr((args, kwargs)))}"


def render_compose(scope: dict[str, Any], flags: dict[str, bool], origin: str) -> str:
    """Render compose.yml.j2 as one writer sees it, lookups and includes stubbed.

    Args:
        scope: the vars in scope at the writer, switches included.
        flags: the feature flags and the probe result.
        origin: ``bootstrap`` for the sys-svc-compose writer, ``final`` for
            the role's own.

    Returns:
        The rendered compose file.
    """
    env = template_action_env(lstrip_blocks=True)
    env.loader = FunctionLoader(lambda name: COMPOSE_INCLUDES.get(name, ""))
    source = read_text(str(COMPOSE_TEMPLATE))
    names = meta.find_undeclared_variables(env.parse(source))
    context: dict[str, Any] = {name: Placeholder(name) for name in names}
    for name in include_chain_vars():
        context.pop(name, None)
        if origin == "bootstrap":
            context[name] = Placeholder(f"{origin}:{name}")
    for name in (*ROLE_SCOPED_NAMES, *scope):
        context[name] = Placeholder(f"{origin}:{name}")
    context.update(zip(SWITCHES, switches_of(scope, flags), strict=True))
    context["lookup"] = compose_lookup
    return env.from_string(source).render(context)


def compose_scopes() -> dict[str, dict[str, Any]]:
    """Return the vars in scope at the bootstrap and the final compose.yml render.

    Returns:
        ``bootstrap``: the scope of the svc-stack include in 00_core.yml that
        reaches sys-svc-compose/tasks/04_files.yml; ``final``: the scope of the
        role's own compose writer.
    """
    bootstrap = next(
        scope
        for task, scope in scoped_tasks_of(STAGE_FILES[0])
        if task.get("include_role") == {"name": STACK_ROLE, "tasks_from": STACK_ENTRY}
    )
    final = next(
        scope
        for path, _task, scope in compose_writers()
        if path.startswith(str(ROLE.relative_to(PROJECT_ROOT)))
    )
    return {"bootstrap": bootstrap, "final": final}


def debug_off_lookup(kind: str, *_args: Any) -> bool:
    """Stand in for ``lookup('debug')``, the only lookup xwiki.properties.j2 calls.

    Args:
        kind: the lookup plugin name; anything but ``debug`` raises.
    """
    if kind != "debug":
        raise AssertionError(f"xwiki.properties.j2 calls an unstubbed lookup('{kind}')")
    return False


def render_properties(stage: dict[str, Any], flags: dict[str, bool]) -> str:
    """Render xwiki.properties.j2 under one stage's switches, every other value stubbed.

    Args:
        stage: the ``vars`` mapping in force at the render.
        flags: the feature flags and the probe result.

    Returns:
        The rendered properties file.
    """
    env = template_action_env(lstrip_blocks=False)
    source = read_text(str(PROPERTIES_TEMPLATE))
    names = meta.find_undeclared_variables(env.parse(source))
    context: dict[str, Any] = {name: Placeholder(name) for name in names}
    context.update(flags)
    context["lookup"] = debug_off_lookup
    context.update(zip(SWITCHES, switches_of(stage, flags), strict=True))
    return env.from_string(source).render(context)


class LenientUndefined(ChainableUndefined, DebugUndefined):
    __slots__ = ()


def container_lookup(kind: str, *args: Any, **_kwargs: Any) -> Any:
    """Stand in for ``lookup`` with the container paths a compose writer may name.

    Args:
        kind: the lookup plugin name.
        args: the lookup terms; the last one is the container key.

    Returns:
        The stubbed path for ``container``, else a placeholder.
    """
    if kind == "container":
        return CONTAINER_PATHS.get(str(args[-1]), f"{INSTANCE_DIR}/{args[-1]}")
    return Placeholder(repr((kind, args)))


def module_args(task: dict[str, Any]) -> dict[str, Any]:
    """Return the arguments of a task's file-writing module.

    Args:
        task: one parsed task mapping.

    Returns:
        The argument mapping of the first module in ``WRITE_MODULES`` it calls.
    """
    return next(task[m] for m in WRITE_MODULES if isinstance(task.get(m), dict))


def compose_writers() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Find every task that writes the XWiki compose.yml, by its rendered target.

    Returns:
        ``(task file, task, block-inherited vars)`` per writer.
    """
    env = jinja(native=False)
    env.undefined = LenientUndefined
    target = os.path.normpath(CONTAINER_PATHS["files.compose"])
    found: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for role in COMPOSE_WRITER_ROLES:
        for path in sorted((role / "tasks").glob("**/*.yml")):
            for task, scope in scoped_tasks_of(path):
                for module in WRITE_MODULES:
                    args = task.get(module)
                    if not isinstance(args, dict) or "dest" not in args:
                        continue
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore", DeprecationWarning)
                            dest = env.from_string(str(args["dest"])).render(
                                application_id="web-app-xwiki",
                                lookup=container_lookup,
                            )
                    except (TemplateError, TypeError):
                        continue
                    if os.path.normpath(dest) == target:
                        found.append((str(path.relative_to(PROJECT_ROOT)), task, scope))
    return found


def expected_switches(flags: dict[str, bool]) -> list[tuple[bool, bool, bool]]:
    """Return the ``(oidc, ldap, s3)`` each render must select, in deploy order.

    Args:
        flags: the feature flags and the probe result.

    Returns:
        The bootstrap, blob-move and final switch tuples.
    """
    ready = flags[READY]
    oidc = flags["XWIKI_OIDC_ENABLED"]
    ldap = flags["XWIKI_LDAP_ENABLED"]
    s3 = flags["XWIKI_OBJSTORE_ENABLED"]
    return [
        (oidc and ready, ldap and ready, s3 and ready),
        (oidc and ready, ldap and ready, s3),
        (oidc, ldap, s3),
    ]


WIKI_STATES = (converged, fresh, without_blob_extension)
STAGE_REASONS = (
    (
        "the bootstrap render boots the wiki before 04_extensions runs, so it may "
        "select an add-on only once the probe found it on its pin, and must select "
        "it then or every redeploy restarts twice"
    ),
    (
        "06_design/logo.yml reads attachments right after the blob-move render, so "
        "the bucket must be on there whatever the probe said, while auth may only "
        "follow the bootstrap render"
    ),
    "the final render carries the configured features",
)


class TestRenderStages(unittest.TestCase):
    def test_a_converged_wiki_renders_the_final_config_at_every_stage(self) -> None:
        stages = render_stages()
        self.assertGreaterEqual(len(stages), 2)
        for flags in inventories(converged):
            final = switches_of(stages[-1], flags)
            for index, stage in enumerate(stages[:-1], start=1):
                with self.subTest(stage=index, **flags):
                    self.assertEqual(
                        switches_of(stage, flags),
                        final,
                        "every render that differs from the final one rewrites "
                        "xwiki.properties, notifies compose-up and force-recreates "
                        "XWiki, then waits ~80 s for REST; on a wiki whose core and "
                        "add-ons already run on their pins that is a restart pair "
                        "per redeploy with nothing changed",
                    )

    def test_every_stage_selects_exactly_its_switches_in_every_wiki_state(
        self,
    ) -> None:
        stages = render_stages()
        self.assertEqual(len(stages), len(STAGE_REASONS))
        for wiki in WIKI_STATES:
            for flags in inventories(wiki):
                expected = expected_switches(flags)
                for index, stage in enumerate(stages):
                    with self.subTest(wiki=wiki.__name__, stage=index, **flags):
                        self.assertEqual(
                            switches_of(stage, flags),
                            expected[index],
                            STAGE_REASONS[index],
                        )

    def test_a_fresh_wiki_fails_the_probe(self) -> None:
        for flags in inventories(fresh):
            with self.subTest(**flags):
                self.assertFalse(flags[READY])

    def test_xwiki_properties_follows_the_switches_at_every_stage(self) -> None:
        stages = render_stages()
        for wiki in WIKI_STATES:
            for flags in inventories(wiki):
                for index, stage in enumerate(stages):
                    oidc, ldap, s3 = switches_of(stage, flags)
                    text = render_properties(stage, flags)
                    with self.subTest(wiki=wiki.__name__, stage=index, **flags):
                        self.assertEqual(
                            "store.blobStoreType=s3" in text,
                            s3,
                            "the blob store lines must follow the stage switch, "
                            "not the inventory flag: a fresh wiki booted on the "
                            "'s3' hint before 04_extensions cannot start",
                        )
                        self.assertEqual(
                            "security.authentication.authService=oidc" in text, oidc
                        )
                        self.assertEqual(
                            "security.authentication.authService=ldap" in text,
                            ldap and not oidc,
                        )

    def test_a_wiki_without_the_blob_extension_boots_off_the_bucket(self) -> None:
        bootstrap = render_stages()[0]
        for flags in inventories(without_blob_extension):
            if not flags["XWIKI_OBJSTORE_ENABLED"]:
                continue
            with self.subTest(**flags):
                self.assertFalse(
                    flags[READY] or switches_of(bootstrap, flags)[2],
                    f"a running wiki without {BLOB_S3} on its pin must fail the "
                    "probe: the bootstrap render boots it on the 's3' blob store "
                    "hint before 04_extensions installs the extension, and "
                    "nothing answers that hint",
                )

    def test_both_compose_renders_use_the_role_template(self) -> None:
        writers = {path: task for path, task, _scope in compose_writers()}
        bootstrap = writers.pop("roles/sys-svc-compose/tasks/04_files.yml")
        self.assertEqual(
            [entry.get("files") for entry in bootstrap["with_first_found"]],
            [[COMPOSE_SOURCE]],
        )
        self.assertFalse(
            (PROJECT_ROOT / "roles/sys-svc-compose" / ROLE_FILE_TEMPL_COMPOSE).exists()
        )
        self.assertEqual(
            [module_args(task).get("src") for task in writers.values()],
            [COMPOSE_SOURCE],
        )

    def test_every_compose_render_selects_its_stage_switches(self) -> None:
        scopes = compose_scopes()
        for wiki in WIKI_STATES:
            for flags in inventories(wiki):
                expected = expected_switches(flags)
                with self.subTest(wiki=wiki.__name__, **flags):
                    self.assertEqual(
                        switches_of(scopes["bootstrap"], flags), expected[0]
                    )
                    self.assertEqual(
                        switches_of(scopes["final"], flags),
                        expected[-1],
                        "compose.yml.j2 carries the XWIKI_CFG_LDAP_* environment, "
                        "and the final compose render is the only one that can "
                        "turn it on for a wiki that was fresh at bootstrap",
                    )

    def test_every_compose_render_is_yaml_carrying_its_environment(self) -> None:
        scopes = {
            **compose_scopes(),
            **{f"stage-{i}": scope for i, scope in enumerate(render_stages())},
        }
        for wiki in WIKI_STATES:
            for flags in inventories(wiki):
                for name, scope in scopes.items():
                    oidc, ldap, _s3 = switches_of(scope, flags)
                    origin = "bootstrap" if name == "bootstrap" else "final"
                    text = render_compose(scope, flags, origin)
                    with self.subTest(wiki=wiki.__name__, render=name, **flags):
                        document = load_yaml_str(text)
                        self.assertIsInstance(document, dict)
                        environment = document["services"]["xwiki"]["environment"]
                        self.assertIn("XWIKI_PROPERTIES_SOURCE", environment)
                        self.assertEqual(
                            {
                                key
                                for key in environment
                                if key.startswith("XWIKI_CFG_LDAP_")
                            },
                            LDAP_KEYS if ldap and not oidc else set(),
                        )

    def test_a_converged_wiki_renders_one_compose_file(self) -> None:
        scopes = compose_scopes()
        for flags in inventories(converged):
            with self.subTest(**flags):
                self.assertEqual(
                    render_compose(scopes["bootstrap"], flags, "bootstrap"),
                    render_compose(scopes["final"], flags, "final"),
                    "sys-svc-compose renders compose.yml.j2 under the bootstrap "
                    "switches and 02_manager_ops.yml renders it again under the "
                    "final ones; any byte that differs flips the file twice per "
                    "redeploy and force-recreates XWiki each time",
                )

    def test_only_the_role_templates_read_the_switches(self) -> None:  # nocheck: test.text-presence -- repository-wide lint over every role template  # fmt: skip
        readers = {
            str(path.relative_to(PROJECT_ROOT))
            for path in PROJECT_ROOT.glob("roles/*/templates/**/*.j2")
            if any(name in read_text(str(path)) for name in SWITCHES)
        }
        self.assertEqual(
            {path for path in readers if not path.startswith("roles/web-app-xwiki/")},
            set(),
            "render_compose stubs every include as empty, which holds only "
            "while no template outside web-app-xwiki reads a switch",
        )

    def test_every_compose_render_writes_mode_0640(self) -> None:
        writers = compose_writers()
        self.assertGreaterEqual(len(writers), 2, writers)
        for path, task, _scope in writers:
            with self.subTest(path=path):
                self.assertEqual(
                    module_args(task).get("mode"),
                    COMPOSE_MODE,
                    "sys-svc-compose writes compose.yml as 0640 and "
                    "stack_host_template defaults to 0644, so any writer with "
                    "another mode flips it back, reports changed and notifies "
                    "compose-up: a force-recreate restart of XWiki on every "
                    "redeploy",
                )


if __name__ == "__main__":
    unittest.main()
