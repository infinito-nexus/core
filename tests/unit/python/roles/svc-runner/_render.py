from __future__ import annotations

import json
import posixpath
import re
from importlib.util import module_from_spec, spec_from_file_location
from typing import TYPE_CHECKING, Any

from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.filter.core import FilterModule
from ansible.plugins.test.core import TestModule
from jinja2 import (
    BaseLoader,
    Environment,
    FunctionLoader,
    StrictUndefined,
    select_autoescape,
)

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_FILE_DEFAULTS_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_META_USERS,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

if TYPE_CHECKING:
    from pathlib import Path

ROLE = PROJECT_ROOT / "roles" / "svc-runner"
FIXTURE = (
    PROJECT_ROOT
    / "tests"
    / "unit"
    / "python"
    / "roles"
    / "svc-runner"
    / "fixtures"
    / "github.json"
)
COMPOSE = posixpath.basename(ROLE_FILE_TEMPL_COMPOSE)
INSTANCE_ENV = "runner_instance_env.j2"
TEST_ENV = "test.env.j2"
SUDOERS = "sudoers.j2"
STAGE_DEST = "entrypoint.sh"
STAGE_MODULES = ("stack_host_copy", "copy", "ansible.builtin.copy")
REAL_LOOKUPS = ("compose_only", "compose_restart", "compose_replicas")
ABSENT_LOOKUPS = ("database", "objstore", "engine", "sso")
LOG_LABEL = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/22_logging.yml"))[
    "DOCKER_LOG_LABEL"
]
PAT = "PAT_SENTINEL"
GIT_REF = "feature/ref-sentinel"
HOME = "/home/operator"
ROOTS = [f"{HOME}/Repositories/core", f"{HOME}/.local/share/worktrees"]
IMAGE_SRC_DIR = "/opt/src/infinito"
SRC_DIR = f"{ROOTS[1]}/github.com/infinito-nexus/core/feature-x"
PLAYBOOK = f"{ROOTS[1]}/github.com/infinito-nexus/core/last-infra-update"
TOOLCHAIN = "infinito/arch:0123abcd"
OPERATOR = 1000
QUEUE = "/var/cache/infinito/core/cache/jobs"
QUEUE_GID = 901
HOST_ENV = {
    "GITHUB_REPOSITORY": "infinito-nexus/core",
    "GITHUB_REPOSITORY_OWNER": "infinito-nexus",
    "GITHUB_TOKEN": PAT,
    "GH_TOKEN": "",
    "INFINITO_SRC_DIR": IMAGE_SRC_DIR,
}
ACCOUNT_LOOKUP = re.compile(r"lookup\('users', '([^']+)'\)")
ANSIBLE_FILTERS = ("regex_escape", "regex_replace")
ANSIBLE_TESTS = ("match", "search")
CAPABILITIES = (
    "RUNNER_ENTRYPOINT",
    "RUNNER_REGISTERS_WITH_GITHUB",
    "RUNNER_MOUNTS_WORKTREES",
    "RUNNER_TAKES_LOCAL_JOBS",
)


def _path_join(parts):
    return posixpath.join(*parts)


def _is_changed(value):
    return bool(value.changed)


def environment(loader: BaseLoader | None = None, lstrip: bool = True) -> Environment:
    """Args:
        loader: the loader include and template lookups resolve against.
        lstrip: the ``lstrip_blocks`` setting of the rendering task.

    Returns:
        A strict environment with the filters and tests the role's templates use.
    """
    env = Environment(
        loader=loader,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=lstrip,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["entity_name"] = entity_name
    env.filters["path_join"] = _path_join
    env.filters["bool"] = boolean
    env.filters["to_json"] = json.dumps
    filters, tests = FilterModule().filters(), TestModule().tests()
    env.filters.update({name: filters[name] for name in ANSIBLE_FILTERS})
    env.tests.update({name: tests[name] for name in ANSIBLE_TESTS})
    env.tests["changed"] = _is_changed
    return env


def condition(expression: str, **variables: Any) -> bool:
    """Args:
        expression: an Ansible ``when`` or ``that`` expression.
        variables: the variables it reads.

    Returns:
        Whether the expression holds.
    """
    template = "{% if " + expression + " %}yes{% else %}no{% endif %}"
    return environment().from_string(template).render(**variables) == "yes"


def lookup_class(name: str):
    """Args:
        name: a lookup plugin below plugins/lookup.

    Returns:
        The plugin's ``LookupModule`` class.
    """
    spec = spec_from_file_location(
        f"svc_runner_render_{name}", PROJECT_ROOT / "plugins" / "lookup" / f"{name}.py"
    )
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LookupModule


def project_template(name: str) -> str:
    """Args:
        name: a template path relative to the repository root.

    Returns:
        The template source.
    """
    return read_text(str(PROJECT_ROOT / name))


def role_vars(role: Path = ROLE) -> dict[str, Any]:
    """Args:
        role: the role directory.

    Returns:
        The role's vars/main.yml.
    """
    return load_yaml_any(str(role / ROLE_FILE_VARS_MAIN))


def runner_account() -> dict[str, Any]:
    """Returns:
    The meta/users.yml entry the role's ``RUNNER_ACCOUNT`` looks up.
    """
    (key,) = ACCOUNT_LOOKUP.findall(role_vars(ROLE)["RUNNER_ACCOUNT"])
    return load_yaml_any(str(ROLE / ROLE_FILE_META_USERS))[key]


def runner_defaults(role: Path = ROLE) -> dict[str, Any]:
    """Args:
        role: the role directory.

    Returns:
        The ``runner`` service defaults of the role's meta/services.yml.
    """
    return load_yaml_any(str(role / ROLE_FILE_META_SERVICES))["runner"]


def flavor_variables(flavor: str, role: Path = ROLE) -> dict[str, Any]:
    """Args:
        flavor: the value of ``services.runner.flavor``.
        role: the role directory.

    Returns:
        ``RUNNER_FLAVOR``, the role's ``RUNNER_FLAVORS`` and every capability
        vars/main.yml derives from them, rendered to text as Ansible renders
        a templated var.
    """
    declared = role_vars(role)
    known = {"RUNNER_FLAVOR": flavor, "RUNNER_FLAVORS": declared["RUNNER_FLAVORS"]}
    env = environment()
    return {
        **known,
        **{
            name: env.from_string(declared[name]).render(known) for name in CAPABILITIES
        },
    }


def source_dir(flavor: str, src_dir: str = SRC_DIR, role: Path = ROLE) -> str:
    """Args:
        flavor: the value of ``services.runner.flavor``.
        src_dir: the value of ``services.runner.src_dir``.
        role: the role directory.

    Returns:
        ``RUNNER_SRC_DIR`` as the role's defaults/main.yml resolves it, with
        ``INFINITO_SRC_DIR`` the toolchain image's path, as in the infra runner.
    """
    expression = load_yaml_any(str(role / ROLE_FILE_DEFAULTS_MAIN))["RUNNER_SRC_DIR"]
    env = environment()

    def lookup(plugin, *terms):
        if plugin == "env":
            return HOST_ENV[terms[0]]
        if plugin == "config" and terms == ("svc-runner", "services.runner.src_dir"):
            return src_dir
        raise AssertionError(f"unexpected lookup {plugin} {terms}")

    env.globals["lookup"] = lookup
    return env.from_string(expression).render(
        application_id="svc-runner",
        playbook_dir=PLAYBOOK,
        **flavor_variables(flavor, role),
    )


def flavor_of(override: dict[str, Any]) -> str:
    """Args:
        override: the ``services.runner`` keys an inventory sets.

    Returns:
        The flavor the merged config resolves, the role default when the inventory sets none.
    """
    return {**runner_defaults(), **override}["flavor"]


def variables(flavor: str, swarm: bool, roots: list[str]) -> dict[str, Any]:
    """Args:
        flavor: the value of ``services.runner.flavor``.
        swarm: render for swarm mode instead of compose mode.
        roots: the value of ``services.runner.worktree_roots``.

    Returns:
        The variables every template of the role reads.
    """
    account = runner_account()
    return {
        "application_id": "svc-runner",
        "compose_mode_force": "compose",
        "DEPLOYMENT_MODE": "swarm" if swarm else "compose",
        "DOCKER_LOG_LABEL": LOG_LABEL,
        "IS_SWARM_MODE": swarm,
        **flavor_variables(flavor),
        "RUNNER_WORKTREE_ROOTS": roots,
        "RUNNER_QUEUE_DIR": QUEUE,
        "RUNNER_QUEUE_GROUP": "runner-queue",
        "RUNNER_QUEUE_GID": QUEUE_GID,
        "RUNNER_COUNT": 2,
        "RUNNER_IMAGE_REF": ("manager:5000/" if swarm else "")
        + "infinito-runner:latest",
        "RUNNER_INSTALL_DIR": "/opt/github-runner",
        "RUNNER_DOCKER_BASE": "/mnt/docker",
        "RUNNER_BASE_IMAGE": "ubuntu:26.04",
        "RUNNER_UID": account["uid"],
        "RUNNER_GID": account["gid"],
        "_runner_docker_gid": "999",
        "RUNNER_PROJECT_PREFIX": "runner",
        "RUNNER_CPUS": 2,
        "RUNNER_NAME": "runner.example",
        "RUNNER_LABELS": "self-hosted,linux,ubuntu",
        "RUNNER_DISTRIBUTION": "ubuntu",
        "RUNNER_GITHUB_OWNER": "infinito-nexus",
        "RUNNER_GITHUB_REPO": "core",
        "RUNNER_API_TOKEN": PAT,
        "RUNNER_GIT_REF": GIT_REF,
        "RUNNER_SRC_DIR": source_dir(flavor),
        "RUNNER_TOOLCHAIN_IMAGE": TOOLCHAIN,
        "RUNNER_OPERATOR_UID": OPERATOR,
        "RUNNER_OPERATOR_GID": OPERATOR,
        "RUNNER_USER": account["username"],
        "DOMAIN_PRIMARY": "infinito.example",
        "DOCKER_IN_CONTAINER": False,
        "DEPLOY_IS_UPDATE": False,
        "INFINITO_GHCR_MIRROR_PREFIX": "",
        "INFINITO_IMAGE_TAG": "latest",
        "runner_instance": 1,
    }


def render(
    name: str,
    flavor: str,
    *,
    swarm: bool = False,
    roots: list[str] | None = None,
    role: Path = ROLE,
    source: str | None = None,
) -> str:
    """Args:
        name: the template file below the role's templates/.
        flavor: the value of ``services.runner.flavor``.
        swarm: render for swarm mode instead of compose mode.
        roots: the worktree roots, ROOTS when None.
        role: the role directory the template is read from.
        source: a replacement template text, for negative controls.

    Returns:
        The rendered template, with the whitespace handling of the task that renders it.
    """
    values = variables(flavor, swarm, ROOTS if roots is None else roots)
    env = environment(FunctionLoader(project_template), lstrip=name == COMPOSE)

    def lookup(plugin, *terms, **kwargs):
        if plugin == "env":
            return HOST_ENV[terms[0]]
        if plugin == "template":
            return env.get_template(terms[0]).render(values)
        if plugin in REAL_LOOKUPS:
            return lookup_class(plugin)().run(list(terms), variables=values, **kwargs)[
                0
            ]
        if plugin in ABSENT_LOOKUPS:
            return False
        if plugin == "container_networks":
            return "networks:\n  default: {}"
        if plugin == "compose_networks":
            return "networks:\n  default:\n    name: runner"
        if plugin == "compose_volumes":
            return ""
        raise AssertionError(f"unexpected lookup {plugin}")

    env.globals["lookup"] = lookup
    text = source if source is not None else read_text(str(role / "templates" / name))
    return env.from_string(text).render(values)


def stage_task(role: Path = ROLE) -> dict[str, Any]:
    """Args:
        role: the role directory.

    Returns:
        The core task that stages the entrypoint into the build context.
    """
    (task,) = [
        task
        for task in load_yaml_any(str(role / "tasks" / "00_core.yml"))
        if any(
            f"'{STAGE_DEST}']" in str((task.get(module) or {}).get("dest", ""))
            for module in STAGE_MODULES
        )
    ]
    return next(task[module] for module in STAGE_MODULES if module in task)


def staged_entrypoint(flavor: str, role: Path = ROLE) -> str:
    """Args:
        flavor: the value of ``services.runner.flavor``.
        role: the role directory.

    Returns:
        The file the stage task copies into the build context.
    """
    src = environment().from_string(stage_task(role)["src"])
    path = src.render(flavor_variables(flavor, role))
    return read_text(str(role / "files" / path))


def renders(flavor: str, role: Path = ROLE) -> dict[str, str]:
    """Args:
        flavor: the value of ``services.runner.flavor``.
        role: the role directory.

    Returns:
        Every file the role renders or stages, keyed by a stable name.
    """
    return {
        "compose": render(COMPOSE, flavor, role=role),
        "compose_swarm": render(COMPOSE, flavor, swarm=True, role=role),
        "instance_env": render(INSTANCE_ENV, flavor, role=role),
        "test_env": render(TEST_ENV, flavor, role=role),
        "sudoers": render(SUDOERS, flavor, role=role),
        "entrypoint": staged_entrypoint(flavor, role),
        "dockerfile": read_text(str(role / "files" / "Dockerfile")),
    }


def fixture() -> dict[str, str]:
    """Returns:
    Every render of the github flavor captured before the flavor existed.
    """
    return json.loads(read_text(str(FIXTURE)))


def env_values(text: str) -> dict[str, str]:
    """Args:
        text: a rendered env file.

    Returns:
        Its ``KEY=value`` assignments.
    """
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
