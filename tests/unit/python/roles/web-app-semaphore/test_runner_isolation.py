"""The dedicated runner runs every template without the Docker socket, root or a key."""

from __future__ import annotations

import copy
import itertools
import re
import unittest

from jinja2 import ChainableUndefined, DictLoader, Environment, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.networks.render import render_compose_networks, render_container_networks
from utils.roles.mapping import (
    ROLE_FILE_META_VOLUMES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles" / "web-app-semaphore"
SERVER_ENV = ROLE / "templates" / "env.j2"
RUNNER_ENV_TEMPLATE = "roles/web-app-semaphore/templates/env/task-runner.j2"
PROVISION_ENV_TEMPLATE = "roles/web-app-semaphore/templates/env/provision-runner.j2"
CONTAINER_ENV_TEMPLATE = "roles/sys-svc-container/templates/env.j2"
RUNNER_ENV = PROJECT_ROOT / RUNNER_ENV_TEMPLATE
EXPORT_RUNNER_ENV = ROLE / "templates" / "env" / "export-runner.j2"
DOCKERFILE = ROLE / "files" / "runner" / "Dockerfile"

RUNNER = "task-runner"
TOKEN_VOLUME = "semaphore_runner_token"
REMOTE_RUNNER_KEY = "SEMAPHORE_USE_REMOTE_RUNNER"
REMOTE_RUNNER_LINE = f"{REMOTE_RUNNER_KEY}=true"
RUNNER_USER = "${SEMAPHORE_RUNNER_UID}:${SEMAPHORE_RUNNER_GID}"
RUNNER_IDS = (("SEMAPHORE_RUNNER_UID", "uid"), ("SEMAPHORE_RUNNER_GID", "gid"))
RUNNER_SERVICE_REF = "{{ SEMAPHORE_RUNNER_SERVICE }}"
BLOCK_START = "{% for runner in SEMAPHORE_PLATFORM_RUNNERS_ACTIVE %}"
BLOCK_END = "{% if SEMAPHORE_EXPORT_RUNNER_ENABLED | bool %}"
SIDECAR_END = "{{ lookup('compose_volumes') }}"
BLOCK_FORBIDDEN = (
    "docker.sock",
    "privileged",
    "user:",
    "volumes:",
    "cap_add",
    "network_mode",
    "pid:",
)
SIDECAR_CAPABILITIES = ["SETUID", "SETGID"]
EXPORT_RUNNER = "export-runner"
EGRESS = "egress"
EXPORT_NETWORK = "export"
EXPORT_ENV_FILE = "/opt/compose/semaphore/env/export-runner.env"
RUNNER_ENV_FILE = "/opt/compose/semaphore/env/task-runner.env"
PROVISION_ENV_FILE = "/opt/compose/semaphore/env/provision-runner.env"
PROVISION_ENV_SELECTOR = (
    "SEMAPHORE_PROVISION_RUNNER_ENV_FILE if runner.key == 'provision' else "
)
INCLUDES = {
    "roles/sys-svc-compose/templates/base.yml.j2": "services:\n",
    "roles/sys-svc-container/templates/base.yml.j2": (
        "    restart: unless-stopped\n"
        "{% if docker_compose_env is defined %}"
        '    env_file:\n      - "{{ docker_compose_env }}"\n'
        "{% endif %}"
    ),
}
PROVISION_RUNNER = "provision-runner"
ACTIVE_RUNNERS = [
    {"service": "task-runner", "name": "semaphore-runner"},
    {"service": "deploy-runner", "name": "semaphore-runner-deploy"},
    {"service": EXPORT_RUNNER, "name": "semaphore-runner-export"},
    {
        "service": PROVISION_RUNNER,
        "name": "semaphore-runner-provision",
        "key": "provision",
    },
]
PROVISION_GUARD = "{% if runner.key == 'provision' %}"
SANDBOX_CAPABILITIES = {"SETUID", "SETGID", "CHOWN"}
SANDBOX_TMPFS = {PROVISION_RUNNER: ("semaphore_provision_sandboxes",)}
SANDBOX_ROOT = "/run/provision"
SANDBOX_PREFIX = "SEMAPHORE_SANDBOX_"
SANDBOX_ENV = (
    "SEMAPHORE_SANDBOX_RUNNER_UID",
    "SEMAPHORE_SANDBOX_UID_BASE",
    "SEMAPHORE_SANDBOX_UID_COUNT",
    "SEMAPHORE_SANDBOX_ROOT",
    "SEMAPHORE_SANDBOX_TMP",
    "SEMAPHORE_SANDBOX_SHARED",
    "SEMAPHORE_SANDBOX_TOFU",
    "SEMAPHORE_SANDBOX_CA",
    "SEMAPHORE_SANDBOX_BAO_ADDR",
    "SEMAPHORE_SANDBOX_BROKER_UID",
    "SEMAPHORE_SANDBOX_BROKER_LOGIN",
)
BROKER_VOLUME = "semaphore_dns_broker_login"
SANDBOX_SHARED = ["/var/tmp", "/dev/shm", "/dev/mqueue"]


def provision_target(volumes: dict, volume: str) -> str:
    (mount,) = [
        mount
        for mount in volumes[volume]["mounts"]
        if mount["service"] == PROVISION_RUNNER
    ]
    return mount["target"]


ENV_FORBIDDEN = ("PRIVATE_KEY", "SSH_KEY", "ssh_key", "BEGIN OPENSSH")
GUARD_OPEN = "{% if SEMAPHORE_DEPLOY_ENABLED | bool %}"
GUARD_CLOSE = "{% endif %}"
SOCKET_VOLUME = "    volumes:\n      - /var/run/docker.sock:/var/run/docker.sock\n"
SERVER_FORBIDDEN_KEYS = ("SEMAPHORE_RUNNER_REGISTRATION_TOKEN",)
GLOBAL_RUNNERS_DISABLED = "SEMAPHORE_DEFAULT_GLOBAL_RUNNERS_MODE=disable"
SERVER_SWITCHES = (
    "SEMAPHORE_DEPLOY_ENABLED",
    "SEMAPHORE_LOGIN_SSO",
    "SEMAPHORE_LOGIN_LDAP",
    "SEMAPHORE_OIDC_ENABLED",
    "SEMAPHORE_LDAP_ENABLED",
)


def _text(path) -> str:
    return read_text(str(path))


def _yaml(relative: str):
    return load_yaml_str(_text(ROLE / relative))


def remote_runner_settings(env: str, flags: dict[str, bool]) -> list[str]:
    """
    Args:
        env: the server's ``templates/env.j2``.
        flags: the switches the template branches on.

    Returns:
        Every ``SEMAPHORE_USE_REMOTE_RUNNER`` line the template renders.
    """
    environment = Environment(
        loader=DictLoader({CONTAINER_ENV_TEMPLATE: "", "env.j2": env}),
        undefined=ChainableUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    environment.filters["bool"] = bool
    environment.filters["dotenv_quote"] = str
    environment.globals["lookup"] = lambda *_args, **_kwargs: "stub"
    rendered = environment.get_template("env.j2").render(**flags)
    return [
        line
        for line in rendered.splitlines()
        if line.startswith(f"{REMOTE_RUNNER_KEY}=")
    ]


def remote_runner_findings(env: str) -> list[str]:
    """
    Args:
        env: the server's ``templates/env.j2``.

    Returns:
        Why the server could still run a template itself under some
        combination of the switches the template branches on.
    """
    renders = [
        remote_runner_settings(env, dict(zip(SERVER_SWITCHES, values, strict=True)))
        for values in itertools.product((False, True), repeat=len(SERVER_SWITCHES))
    ]
    if all(settings != [REMOTE_RUNNER_LINE] for settings in renders):
        return [f"expected exactly {REMOTE_RUNNER_LINE}, found {renders[0]}"]
    if any(settings != [REMOTE_RUNNER_LINE] for settings in renders):
        return [f"{REMOTE_RUNNER_LINE} is set only under a condition"]
    return []


def platform_runners(variables: dict) -> dict[str, str]:
    """Args:
    variables: the role's ``vars/main.yml``.

    Returns:
        ``{service: token volume}`` of every platform runner.
    """
    return {
        entry["service"].replace(
            RUNNER_SERVICE_REF, variables["SEMAPHORE_RUNNER_SERVICE"]
        ): entry["volume"]
        for entry in variables["SEMAPHORE_PLATFORM_RUNNERS"]
    }


SCRATCH_VOLUMES = ("semaphore_runner_tmp", "semaphore_runner_work")
READ_ONLY_BINDS = {"provision-runner": ("semaphore_provision_catalogs",)}
HOME_TMPFS = {EXPORT_RUNNER: ("semaphore_export_runner_home",)}
BROKER_SECRETS = {"provision-runner": (BROKER_VOLUME,)}


def runner_volume_findings(volumes: dict, runners: dict[str, str]) -> list[str]:
    """Args:
        volumes: the role's ``meta/volumes.yml``.
        runners: :func:`platform_runners`.

    Returns:
        Every mount of a platform runner beyond its own runner token, its tmpfs
        scratch, its ``HOME_TMPFS``, its ``READ_ONLY_BINDS`` and its
        ``BROKER_SECRETS``.
    """
    findings = []
    for service, token in runners.items():
        mounted = sorted(
            name
            for name, entry in volumes.items()
            if any(mount.get("service") == service for mount in entry.get("mounts", []))
        )
        binds = READ_ONLY_BINDS.get(service, ())
        homes = HOME_TMPFS.get(service, ()) + SANDBOX_TMPFS.get(service, ())
        brokers = BROKER_SECRETS.get(service, ())
        expected = sorted([token, *SCRATCH_VOLUMES, *binds, *homes, *brokers])
        if mounted != expected:
            findings.append(f"{service} mounts {mounted}, expected only {expected}")
        elif volumes[token].get("type") != "secret":
            findings.append(f"{token} is no secret")
        findings.extend(
            f"{name} is no 0400 secret of a uid beside the runner's"
            for name in brokers
            if volumes[name].get("type") != "secret"
            or str(volumes[name].get("mode")) != "0400"
            or volumes[name].get("uid") in (0, volumes[token].get("uid"))
        )
        findings.extend(
            f"{name} is no tmpfs"
            for name in homes
            if volumes[name].get("type") != "tmpfs"
        )
        findings.extend(
            f"{name} is no read-only bind"
            for name in binds
            if name in volumes
            and not (
                volumes[name].get("type") == "bind" and volumes[name].get("read_only")
            )
        )
    findings.extend(
        f"{name} is no tmpfs"
        for name in SCRATCH_VOLUMES
        if volumes.get(name, {}).get("type") != "tmpfs"
    )
    return findings


def runner_block_findings(compose: str) -> list[str]:
    """Return every literal of the runner service that widens its reach.

    Args:
        compose: the role's ``templates/compose.yml.j2``.
    """
    block = compose[compose.index(BLOCK_START) : compose.index(BLOCK_END)]
    if PROVISION_GUARD in block:
        start = block.index(PROVISION_GUARD)
        end = block.index("{% endif %}", start)
        block = block[:start] + block[end:]
    sidecar = compose[compose.index(BLOCK_END) : compose.index(SIDECAR_END)]
    return [
        f"the {RUNNER} service sets {token}"
        for token in BLOCK_FORBIDDEN
        if token in block
    ] + [
        f"the {EGRESS} service sets {token}"
        for token in BLOCK_FORBIDDEN
        if token in sidecar and token != "cap_add"
    ]


def network_context(mode: str) -> dict:
    """Args:
    mode: compose or swarm.

    Returns:
        The arguments of the network renderers for a role with a subnet.
    """
    return {
        "application_id": "web-app-semaphore",
        "deployment_mode": mode,
        "registry": {},
        "entity_name": lambda role: role.rsplit("-", 1)[-1],
        "lookup_config": lambda app, path, default: (
            "192.168.216.0/24" if path == "networks.local.subnet" else default
        ),
        "lookup_database": lambda app, key: "",
    }


def render_compose(compose: str, variables: dict, mode: str, runners: list[dict]):
    """Args:
    compose: the role's ``templates/compose.yml.j2``, possibly planted.
    variables: the role's ``vars/main.yml``.
    mode: compose or swarm.
    runners: ``SEMAPHORE_PLATFORM_RUNNERS_ACTIVE``.

    Returns:
        The compose file, rendered as ``stack_host_template`` renders it, with
        the networks of the real renderers and stubs for every other lookup.
    """
    context = network_context(mode)

    def lookup(name, *terms, **kwargs):
        if name == "container_networks":
            return render_container_networks(**context, **kwargs)
        if name == "compose_networks":
            internal = tuple(kwargs.pop("internal", ()))
            return render_compose_networks(**context, internal=internal, **kwargs)
        if name == "container_extra_hosts":
            return "\nextra_hosts:\n  - host.docker.internal:host-gateway"
        if name == "container_image":
            return f'image: "{terms[1]}:{kwargs.get("version", "pinned")}"'
        if name == "compose_only":
            return f"{terms[0]}: {terms[1]}"
        return ""

    environment = Environment(
        loader=DictLoader(INCLUDES),
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
    )
    environment.globals["lookup"] = lookup
    environment.filters["bool"] = bool
    export = variables["SEMAPHORE_EXPORT_RUNNER_SERVICE"]
    enabled = any(runner["service"] == export for runner in runners)
    text = environment.from_string(compose).render(
        application_id="web-app-semaphore",
        DOCKER_BIND_HOST="127.0.0.1",
        SEMAPHORE_SERVICE="semaphore",
        SEMAPHORE_NAME="semaphore",
        SEMAPHORE_RUNNER_SERVICE=variables["SEMAPHORE_RUNNER_SERVICE"],
        SEMAPHORE_RUNNER_IMAGE_TAG="v17.0.0",
        SEMAPHORE_RUNNER_BUILD_DIR="/opt/compose/semaphore/runner",
        SEMAPHORE_RUNNER_BUILD_ARGS={},
        SEMAPHORE_RUNNER_ENV_FILE=RUNNER_ENV_FILE,
        SEMAPHORE_EXPORT_RUNNER_ENV_FILE=EXPORT_ENV_FILE,
        SEMAPHORE_PROVISION_RUNNER_ENV_FILE=PROVISION_ENV_FILE,
        SEMAPHORE_PLATFORM_RUNNERS_ACTIVE=runners,
        SEMAPHORE_EXPORT_RUNNER_SERVICE=export,
        SEMAPHORE_EXPORT_RUNNER_ENABLED=enabled,
        SEMAPHORE_EXPORT_NETWORK=variables["SEMAPHORE_EXPORT_NETWORK"],
        SEMAPHORE_EXPORT_NETWORKS=[variables["SEMAPHORE_EXPORT_NETWORK"]]
        if enabled
        else [],
        SEMAPHORE_EGRESS_SERVICE=variables["SEMAPHORE_EGRESS_SERVICE"],
        SEMAPHORE_EGRESS_NAME="semaphore-egress",
        SEMAPHORE_SANDBOX_ENTRYPOINT=variables["SEMAPHORE_SANDBOX_ENTRYPOINT"],
    )
    return load_yaml_str(text)


def render_env(template: str, variables: dict, provision_env: str) -> dict[str, str]:
    """Args:
    template: :data:`RUNNER_ENV_TEMPLATE` or :data:`PROVISION_ENV_TEMPLATE`.
    variables: the role's ``vars/main.yml``, possibly planted.
    provision_env: the text of ``templates/env/provision-runner.j2``,
        possibly planted.

    Returns:
        ``{name: value}`` of the env file ``template`` renders to, the
        container env base left out.
    """
    volumes = _yaml(ROLE_FILE_META_VOLUMES)
    environment = Environment(
        loader=DictLoader(
            {
                RUNNER_ENV_TEMPLATE: _text(RUNNER_ENV),
                PROVISION_ENV_TEMPLATE: provision_env,
                CONTAINER_ENV_TEMPLATE: "",
            }
        ),
        autoescape=select_autoescape(default_for_string=False),
        trim_blocks=True,
    )
    environment.filters["bool"] = bool
    text = environment.get_template(template).render(
        SEMAPHORE_RUNNER_SERVER_URL="http://semaphore:3000",
        SEMAPHORE_RUNNER_TMP="/tmp/semaphore",
        SEMAPHORE_RUNNER_TOKEN_FILE="/run/secrets/semaphore-runner-token",
        SEMAPHORE_DEPLOY_ENABLED=False,
        SEMAPHORE_RUNNER_UID=volumes[TOKEN_VOLUME]["uid"],
        SEMAPHORE_SANDBOX_UID_BASE=variables["SEMAPHORE_SANDBOX_UID_BASE"],
        SEMAPHORE_SANDBOX_UID_COUNT=variables["SEMAPHORE_SANDBOX_UID_COUNT"],
        SEMAPHORE_SANDBOX_ROOT=provision_target(
            volumes, "semaphore_provision_sandboxes"
        ),
        SEMAPHORE_SANDBOX_TMP=provision_target(volumes, "semaphore_runner_tmp"),
        SEMAPHORE_SANDBOX_SHARED=variables["SEMAPHORE_SANDBOX_SHARED"],
        SEMAPHORE_SANDBOX_TOFU=variables["SEMAPHORE_SANDBOX_TOFU"],
        SEMAPHORE_SANDBOX_CA="",
        SEMAPHORE_SANDBOX_BAO_ADDR="https://openbao.example.org",
        SEMAPHORE_DNS_BROKER_UID=volumes[BROKER_VOLUME]["uid"],
        SEMAPHORE_DNS_BROKER_LOGIN=provision_target(volumes, BROKER_VOLUME),
    )
    pairs = [line.split("=", 1) for line in text.splitlines() if "=" in line]
    return dict(pairs)


def sandbox_service_findings(
    project: dict, volumes: dict, environment: dict, runner_env: dict
) -> list[str]:
    """Args:
    project: :func:`render_compose`, possibly planted.
    volumes: the role's ``meta/volumes.yml``, possibly planted.
    environment: :func:`render_env` of the provision runner's env file,
        possibly planted.
    runner_env: :func:`render_env` of the env file of the other runners.

    Returns:
        Why the provision runner holds more than the sandbox of 135 needs, or
        less, why it misses a setting every runner gets, and why another
        runner no longer starts as the runner's uid.
    """
    services = project["services"]
    runner = services[PROVISION_RUNNER]
    findings = []
    if runner.get("env_file") != [PROVISION_ENV_FILE]:
        findings.append(f"the provision runner reads {runner.get('env_file')}")
    lost = sorted(
        name for name, value in runner_env.items() if environment.get(name) != value
    )
    if lost:
        findings.append(f"the provision runner loses {lost} of the runner env")
    if runner.get("user") != "0:0":
        findings.append(f"the provision runner starts as {runner.get('user')}")
    if runner.get("cap_drop") != ["ALL"]:
        findings.append("the provision runner keeps every default capability")
    added = set(runner.get("cap_add") or [])
    if not added <= SANDBOX_CAPABILITIES:
        extra = sorted(added - SANDBOX_CAPABILITIES)
        findings.append(f"the provision runner adds {extra}")
    options = runner.get("security_opt") or []
    if "no-new-privileges:true" not in options:
        findings.append("the provision runner gains new privileges")
    if any(option.startswith(("seccomp", "apparmor")) for option in options):
        findings.append("the provision runner leaves Docker's default profiles")
    layout = sorted(name for name in environment if name.startswith(SANDBOX_PREFIX))
    if layout != sorted(SANDBOX_ENV):
        findings.append("the spawner lacks the layout of its sandboxes")
    elif environment["SEMAPHORE_SANDBOX_SHARED"].split(":") != SANDBOX_SHARED:
        shared = environment["SEMAPHORE_SANDBOX_SHARED"]
        findings.append(f"the spawner closes {shared} only")
    (tmp,) = [
        mount
        for mount in volumes["semaphore_runner_tmp"]["mounts"]
        if mount["service"] == PROVISION_RUNNER
    ]
    if str(tmp.get("mode")) != "0700":
        findings.append(f"/tmp of the provision runner has mode {tmp.get('mode')}")
    sandboxes = volumes.get("semaphore_provision_sandboxes", {})
    (root,) = [
        mount
        for mount in sandboxes.get("mounts", [{"service": PROVISION_RUNNER}])
        if mount["service"] == PROVISION_RUNNER
    ]
    if sandboxes.get("type") != "tmpfs" or root.get("target") != SANDBOX_ROOT:
        findings.append(f"{SANDBOX_ROOT} is no tmpfs of the provision runner")
    elif str(root.get("mode")) != "0711":
        findings.append(f"{SANDBOX_ROOT} has mode {root.get('mode')}")
    for name, service in sorted(services.items()):
        if name != PROVISION_RUNNER and ("user" in service or "entrypoint" in service):
            findings.append(f"{name} no longer starts as the runner uid")
    return findings


def uid_range_findings(variables: dict, volumes: dict) -> list[str]:
    """Args:
    variables: the role's ``vars/main.yml``, possibly planted.
    volumes: the role's ``meta/volumes.yml``.

    Returns:
        Why a sandbox uid could be the runner's uid or a workspace runner's;
        the workspace runners count up from their base without a cap, so the
        range must end below that base.
    """
    base = int(variables["SEMAPHORE_SANDBOX_UID_BASE"])
    count = int(variables["SEMAPHORE_SANDBOX_UID_COUNT"])
    uids = range(base, base + count)
    findings = []
    if base <= 0 or count <= 0:
        findings.append(f"the sandbox uids {base}+{count} hold root or none")
    if volumes[TOKEN_VOLUME]["uid"] in uids:
        findings.append("the sandbox uids hold the runner uid")
    if uids.stop > int(variables["SEMAPHORE_WORKSPACE_UID_BASE"]):
        findings.append("the sandbox uids reach the workspace runner uids")
    broker = volumes[BROKER_VOLUME]["uid"]
    if broker in uids:
        findings.append("the sandbox uids hold the broker uid")
    if broker in (0, volumes[TOKEN_VOLUME]["uid"]) or broker >= int(
        variables["SEMAPHORE_WORKSPACE_UID_BASE"]
    ):
        findings.append("the broker uid is root, the runner's or a workspace runner's")
    return findings


def export_shape_findings(project: dict) -> list[str]:
    """Args:
    project: :func:`render_compose`, possibly planted.

    Returns:
        Why the export runner lacks the workspace runner shape, has a route
        out beside its egress proxy, or why another member of its network
        has one.
    """
    services = project["services"]
    runner = services[EXPORT_RUNNER]
    findings = []
    if runner.get("read_only") is not True:
        findings.append("the export runner writes its root filesystem")
    if runner.get("cap_drop") != ["ALL"] or runner.get("cap_add"):
        findings.append("the export runner keeps capabilities")
    if "no-new-privileges:true" not in runner.get("security_opt", []):
        findings.append("the export runner gains new privileges")
    if runner.get("extra_hosts"):
        findings.append("the export runner has extra hosts")
    if runner.get("env_file") != [EXPORT_ENV_FILE]:
        findings.append(f"the export runner reads {runner.get('env_file')}")
    members = sorted(
        name
        for name, service in services.items()
        if EXPORT_NETWORK in (service.get("networks") or {})
    )
    if members != sorted([EXPORT_RUNNER, EGRESS]):
        findings.append(f"the export network holds {members}")
    for name in members:
        outside = sorted(set(services[name].get("networks") or {}) - {EXPORT_NETWORK})
        expected = ["default"] if name == EGRESS else []
        if outside != expected:
            findings.append(f"{name} joins {outside} beside the export network")
    if project["networks"][EXPORT_NETWORK].get("internal") is not True:
        findings.append("the export network has a route out")
    egress = services[EGRESS]
    if egress.get("cap_add") != SIDECAR_CAPABILITIES or egress.get("cap_drop") != [
        "ALL"
    ]:
        findings.append("the egress proxy keeps capabilities beyond SETUID and SETGID")
    if egress.get("read_only") is not True:
        findings.append("the egress proxy writes its root filesystem")
    return findings


def runner_user_findings(dockerfile: str, variables: dict, volumes: dict) -> list[str]:
    """Return why a platform runner could run as root or fail to read its token.

    Args:
        dockerfile: the runner's Dockerfile.
        variables: the role's ``vars/main.yml``.
        volumes: the role's ``meta/volumes.yml``.
    """
    users = re.findall(r"(?m)^USER\s+(\S+)\s*$", dockerfile)
    if not users or users[-1] != RUNNER_USER:
        return [f"the last USER is {users[-1:]}, expected {RUNNER_USER}"]
    findings = []
    for name, field in RUNNER_IDS:
        source = f"lookup('volume', application_id, '{TOKEN_VOLUME}').{field}"
        if source not in str(variables.get(name)):
            findings.append(f"{name} does not read the {field} of {TOKEN_VOLUME}")
        value = volumes[TOKEN_VOLUME].get(field)
        if not isinstance(value, int) or value <= 0:
            findings.append(
                f"the {field} of {TOKEN_VOLUME} is {value!r}, not an unprivileged id"
            )
        findings.extend(
            f"the {field} of {token} is not the {field} of {TOKEN_VOLUME}"
            for token in platform_runners(variables).values()
            if volumes[token].get(field) != value
        )
    return findings


def server_runner_findings(env: str) -> list[str]:
    """Args:
    env: the server's ``templates/env.j2``.

    Returns:
        Every setting that would let a runner register itself or turn global
        runners off.
    """
    findings = [
        f"the server env sets {key}" for key in SERVER_FORBIDDEN_KEYS if key in env
    ]
    findings.extend(
        f"the server env sets {line}"
        for line in env.splitlines()
        if line.replace(" ", "") == GLOBAL_RUNNERS_DISABLED
    )
    return findings


def runner_env_findings(env: str) -> list[str]:
    """Return every key material the runner environment carries.

    Args:
        env: the runner's ``templates/env/task-runner.j2``.
    """
    return [
        f"the runner env carries {token}" for token in ENV_FORBIDDEN if token in env
    ]


class TestRunnerIsolation(unittest.TestCase):
    def setUp(self):
        self.server_env = _text(SERVER_ENV)
        self.runner_env = _text(RUNNER_ENV)
        self.compose = _text(ROLE / ROLE_FILE_TEMPL_COMPOSE)
        self.dockerfile = _text(DOCKERFILE)
        self.variables = _yaml(ROLE_FILE_VARS_MAIN)
        self.volumes = _yaml(ROLE_FILE_META_VOLUMES)

    def test_the_server_hands_every_template_to_the_runner(self):
        self.assertEqual(remote_runner_findings(self.server_env), [])

    def test_the_runner_mounts_only_its_token(self):
        self.assertEqual(
            runner_volume_findings(self.volumes, platform_runners(self.variables)), []
        )
        self.assertEqual(len(platform_runners(self.variables)), 5)

    def test_negative_control_a_runner_mounting_another_runners_token_is_reported(self):
        volumes = copy.deepcopy(self.volumes)
        volumes["semaphore_deploy_runner_token"]["mounts"].append(
            {"service": "export-runner", "target": "/run/secrets/deploy"}
        )
        self.assertEqual(
            runner_volume_findings(volumes, platform_runners(self.variables)),
            [
                (
                    "export-runner mounts ['semaphore_deploy_runner_token', "
                    "'semaphore_export_runner_home', 'semaphore_export_runner_token', "
                    "'semaphore_runner_tmp', 'semaphore_runner_work'], expected only "
                    "['semaphore_export_runner_home', 'semaphore_export_runner_token', "
                    "'semaphore_runner_tmp', 'semaphore_runner_work']"
                )
            ],
        )

    def test_negative_control_a_writable_catalog_bind_is_reported(self):
        volumes = copy.deepcopy(self.volumes)
        volumes["semaphore_provision_catalogs"]["read_only"] = False
        self.assertEqual(
            runner_volume_findings(volumes, platform_runners(self.variables)),
            ["semaphore_provision_catalogs is no read-only bind"],
        )

    def test_negative_control_an_export_runner_writing_to_disk_is_reported(self):
        volumes = copy.deepcopy(self.volumes)
        volumes["semaphore_runner_tmp"]["mounts"] = [
            mount
            for mount in volumes["semaphore_runner_tmp"]["mounts"]
            if mount["service"] != "export-runner"
        ]
        volumes["semaphore_runner_work"]["type"] = "volume"
        self.assertEqual(
            runner_volume_findings(volumes, platform_runners(self.variables)),
            [
                (
                    "export-runner mounts ['semaphore_export_runner_home', "
                    "'semaphore_export_runner_token', 'semaphore_runner_work'], expected only "
                    "['semaphore_export_runner_home', 'semaphore_export_runner_token', "
                    "'semaphore_runner_tmp', 'semaphore_runner_work']"
                ),
                "semaphore_runner_work is no tmpfs",
            ],
        )

    def test_negative_control_a_runner_token_of_another_owner_is_reported(self):
        volumes = copy.deepcopy(self.volumes)
        volumes["semaphore_workspaces_runner_token"]["uid"] = 64102
        self.assertEqual(
            runner_user_findings(self.dockerfile, self.variables, volumes),
            [
                "the uid of semaphore_workspaces_runner_token is not the uid of semaphore_runner_token"
            ],
        )

    def test_the_runner_service_adds_no_mount_privilege_or_user(self):
        self.assertEqual(runner_block_findings(self.compose), [])

    def test_the_runner_runs_as_an_unprivileged_user(self):
        self.assertEqual(
            runner_user_findings(self.dockerfile, self.variables, self.volumes), []
        )

    def test_the_runner_env_carries_no_key(self):
        self.assertEqual(runner_env_findings(self.runner_env), [])

    def test_negative_control_a_local_runner_is_reported(self):
        drifted = self.server_env.replace(
            REMOTE_RUNNER_LINE, f"{REMOTE_RUNNER_KEY}=false"
        )
        self.assertNotEqual(drifted, self.server_env)
        self.assertTrue(remote_runner_findings(drifted))

    def test_negative_control_a_conditional_remote_runner_is_reported(self):
        guarded = f"{GUARD_OPEN}\n{REMOTE_RUNNER_LINE}\n{GUARD_CLOSE}"
        drifted = self.server_env.replace(REMOTE_RUNNER_LINE, guarded)
        self.assertEqual(
            remote_runner_findings(drifted),
            [f"{REMOTE_RUNNER_LINE} is set only under a condition"],
        )

    def test_negative_control_a_docker_socket_mount_is_reported(self):
        volumes = copy.deepcopy(self.volumes)
        volumes["docker_socket"] = {
            "type": "bind",
            "source": "/var/run/docker.sock",
            "mounts": [{"service": RUNNER, "target": "/var/run/docker.sock"}],
        }
        self.assertEqual(
            len(runner_volume_findings(volumes, platform_runners(self.variables))), 1
        )

    def test_negative_control_a_literal_socket_volume_is_reported(self):
        drifted = self.compose.replace(BLOCK_END, SOCKET_VOLUME + BLOCK_END)
        self.assertEqual(
            runner_block_findings(drifted),
            [
                f"the {RUNNER} service sets docker.sock",
                f"the {RUNNER} service sets volumes:",
            ],
        )

    def test_negative_control_a_root_user_is_reported(self):
        drifted = self.dockerfile.replace(
            "\nENTRYPOINT ", "\nUSER root\nENTRYPOINT ", 1
        )
        self.assertEqual(
            runner_user_findings(drifted, self.variables, self.volumes),
            [f"the last USER is ['root'], expected {RUNNER_USER}"],
        )

    def test_negative_control_a_root_uid_is_reported(self):
        volumes = copy.deepcopy(self.volumes)
        for token in platform_runners(self.variables).values():
            volumes[token]["uid"] = 0
        self.assertEqual(
            runner_user_findings(self.dockerfile, self.variables, volumes),
            [f"the uid of {TOKEN_VOLUME} is 0, not an unprivileged id"],
        )

    def test_the_server_runs_no_task_itself(self):
        self.assertEqual(remote_runner_findings(self.server_env), [])
        self.assertEqual(
            [f for f in server_runner_findings(self.server_env) if "MODE" in f], []
        )

    def test_the_server_holds_no_registration_token(self):
        self.assertEqual(server_runner_findings(self.server_env), [])

    def test_negative_control_a_registration_token_is_reported(self):
        drifted = f"{self.server_env}SEMAPHORE_RUNNER_REGISTRATION_TOKEN=x\n"
        self.assertEqual(
            server_runner_findings(drifted),
            ["the server env sets SEMAPHORE_RUNNER_REGISTRATION_TOKEN"],
        )

    def test_negative_control_disabled_global_runners_are_reported(self):
        drifted = f"{self.server_env}{GLOBAL_RUNNERS_DISABLED}\n"
        self.assertEqual(
            server_runner_findings(drifted),
            [f"the server env sets {GLOBAL_RUNNERS_DISABLED}"],
        )

    def test_negative_control_a_key_in_the_runner_env_is_reported(self):
        drifted = f"{self.runner_env}SEMAPHORE_APP_CONTROL_PRIVATE_KEY=x\n"
        self.assertEqual(
            runner_env_findings(drifted), ["the runner env carries PRIVATE_KEY"]
        )

    def render(self, compose=None, mode="compose", runners=ACTIVE_RUNNERS):
        return render_compose(
            self.compose if compose is None else compose, self.variables, mode, runners
        )

    def test_the_export_runner_has_the_workspace_runner_shape(self):
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                self.assertEqual(export_shape_findings(self.render(mode=mode)), [])
        network = self.render(mode="swarm")["networks"][EXPORT_NETWORK]
        self.assertEqual(network["driver"], "overlay")
        self.assertEqual(self.render()["networks"][EXPORT_NETWORK]["driver"], "bridge")

    def test_the_other_platform_runners_keep_their_shape(self):
        services = self.render()["services"]
        for name in ("task-runner", "deploy-runner"):
            with self.subTest(name):
                runner = services[name]
                self.assertNotIn("read_only", runner)
                self.assertEqual(sorted(runner["networks"]), ["default"])
                self.assertTrue(runner["extra_hosts"])
                self.assertEqual(runner["env_file"], [RUNNER_ENV_FILE])

    def test_without_the_export_runner_no_egress_proxy_or_export_network_renders(self):
        project = self.render(runners=ACTIVE_RUNNERS[:2])
        self.assertNotIn(EGRESS, project["services"])
        self.assertNotIn(EXPORT_NETWORK, project["networks"])

    def test_negative_control_an_export_runner_with_a_route_out_is_reported(self):
        call = "lookup('container_networks', internal=SEMAPHORE_EXPORT_NETWORK)"
        planted = self.compose.replace(
            call,
            "lookup('container_networks', internal=SEMAPHORE_EXPORT_NETWORK, egress=True)",
        )
        self.assertNotEqual(planted, self.compose)
        self.assertEqual(
            export_shape_findings(self.render(planted)),
            [f"{EXPORT_RUNNER} joins ['default'] beside the export network"],
        )

    def test_negative_control_an_export_runner_without_read_only_is_reported(self):
        guard = "{% if service_name == SEMAPHORE_EXPORT_RUNNER_SERVICE %}\n"
        planted = self.compose.replace(f"{guard}    read_only: true\n", guard)
        self.assertNotEqual(planted, self.compose)
        self.assertEqual(
            export_shape_findings(self.render(planted)),
            ["the export runner writes its root filesystem"],
        )

    def test_negative_control_a_third_member_of_the_export_network_is_reported(self):
        project = self.render()
        project["services"]["task-runner"]["networks"][EXPORT_NETWORK] = {}
        self.assertEqual(
            export_shape_findings(project),
            [
                "the export network holds ['egress', 'export-runner', 'task-runner']",
                "task-runner joins ['default'] beside the export network",
            ],
        )

    def test_the_export_runner_polls_through_its_proxy_one_task_at_a_time(self):
        env = _text(EXPORT_RUNNER_ENV)
        self.assertEqual(runner_env_findings(env), [])
        for line in (
            "SEMAPHORE_WEB_ROOT={{ SEMAPHORE_WEB_ROOT }}",
            "SEMAPHORE_RUNNER_ONE_OFF=true",
            "SEMAPHORE_RUNNER_MAX_PARALLEL_TASKS=1",
        ):
            with self.subTest(line):
                self.assertIn(line, env.splitlines())
        rows = {
            entry["key"]: entry["max_parallel_tasks"]
            for entry in self.variables["SEMAPHORE_PLATFORM_RUNNERS"]
        }
        self.assertEqual(rows["export"], 1)

    def project_findings(
        self, project, volumes=None, variables=None, provision_env=None
    ):
        variables = variables or self.variables
        provision_env = provision_env or _text(PROJECT_ROOT / PROVISION_ENV_TEMPLATE)
        return sandbox_service_findings(
            project,
            volumes or self.volumes,
            render_env(PROVISION_ENV_TEMPLATE, variables, provision_env),
            render_env(RUNNER_ENV_TEMPLATE, variables, provision_env),
        )

    def sandbox_findings(self, compose=None, volumes=None, mode="compose"):
        return self.project_findings(self.render(compose, mode), volumes)

    def test_the_provision_runner_grants_the_sandbox_only_what_it_needs(self):
        for mode in ("compose", "swarm"):
            with self.subTest(mode=mode):
                self.assertEqual(self.sandbox_findings(mode=mode), [])
        entry = self.render()["services"][PROVISION_RUNNER]["entrypoint"]
        self.assertEqual(entry, [self.variables["SEMAPHORE_SANDBOX_ENTRYPOINT"]])

    def planted(self, old, new):
        planted = self.compose.replace(old, new)
        self.assertNotEqual(planted, self.compose, old)
        return planted

    def test_negative_control_a_provision_runner_reading_the_shared_runner_env(self):
        planted = self.planted(PROVISION_ENV_SELECTOR, "")
        self.assertEqual(
            self.sandbox_findings(planted),
            [f"the provision runner reads {[RUNNER_ENV_FILE]}"],
        )

    def test_negative_control_a_provision_env_without_the_runner_env(self):
        text = _text(PROJECT_ROOT / PROVISION_ENV_TEMPLATE)
        include = f"{{% include '{RUNNER_ENV_TEMPLATE}' %}}\n"
        self.assertIn(include, text)
        findings = self.project_findings(
            self.render(), provision_env=text.replace(include, "")
        )
        self.assertEqual(
            findings,
            [
                (
                    "the provision runner loses ['SEMAPHORE_RUNNER_TOKEN_FILE', "
                    "'SEMAPHORE_TMP_PATH', 'SEMAPHORE_WEB_ROOT'] of the runner env"
                )
            ],
        )

    def test_negative_control_an_env_file_without_a_layout_name(self):
        text = _text(PROJECT_ROOT / PROVISION_ENV_TEMPLATE)
        line = "SEMAPHORE_SANDBOX_BAO_ADDR={{ SEMAPHORE_SANDBOX_BAO_ADDR }}\n"
        self.assertIn(line, text)
        findings = self.project_findings(
            self.render(), provision_env=text.replace(line, "")
        )
        self.assertEqual(findings, ["the spawner lacks the layout of its sandboxes"])

    def test_negative_control_a_provision_runner_keeping_capabilities(self):
        kept = "    cap_add:\n      - SETUID\n      - SETGID\n      - CHOWN\n"
        planted = self.planted("    cap_drop:\n      - ALL\n" + kept, kept)
        self.assertEqual(
            self.sandbox_findings(planted),
            ["the provision runner keeps every default capability"],
        )

    def test_negative_control_a_provision_runner_adding_a_capability(self):
        planted = self.planted("      - CHOWN\n", "      - CHOWN\n      - SYS_ADMIN\n")
        self.assertEqual(
            self.sandbox_findings(planted), ["the provision runner adds ['SYS_ADMIN']"]
        )

    def test_negative_control_a_provision_runner_gaining_privileges(self):
        project = self.render()
        project["services"][PROVISION_RUNNER]["security_opt"] = []
        self.assertEqual(
            self.project_findings(project),
            ["the provision runner gains new privileges"],
        )

    def test_negative_control_a_provision_runner_without_the_default_seccomp(self):
        project = self.render(mode="swarm")
        project["services"][PROVISION_RUNNER]["security_opt"].append(
            "seccomp:unconfined"
        )
        self.assertEqual(
            self.project_findings(project),
            ["the provision runner leaves Docker's default profiles"],
        )

    def test_negative_control_a_shared_tmp_of_the_provision_runner(self):
        volumes = copy.deepcopy(self.volumes)
        for mount in volumes["semaphore_runner_tmp"]["mounts"]:
            if mount["service"] == PROVISION_RUNNER:
                mount["mode"] = "1777"
        self.assertEqual(
            self.sandbox_findings(volumes=volumes),
            ["/tmp of the provision runner has mode 1777"],
        )

    def test_negative_control_task_directories_without_their_tmpfs(self):
        volumes = copy.deepcopy(self.volumes)
        del volumes["semaphore_provision_sandboxes"]
        self.assertEqual(
            self.sandbox_findings(volumes=volumes),
            [f"{SANDBOX_ROOT} is no tmpfs of the provision runner"],
        )
        volumes = copy.deepcopy(self.volumes)
        volumes["semaphore_provision_sandboxes"]["mounts"][0]["mode"] = "1777"
        self.assertEqual(
            self.sandbox_findings(volumes=volumes), [f"{SANDBOX_ROOT} has mode 1777"]
        )

    def test_negative_control_another_runner_starting_as_root(self):
        project = self.render()
        project["services"]["task-runner"]["user"] = "0:0"
        self.assertEqual(
            self.project_findings(project),
            ["task-runner no longer starts as the runner uid"],
        )

    def test_negative_control_a_shared_directory_left_open(self):
        variables = copy.deepcopy(self.variables)
        variables["SEMAPHORE_SANDBOX_SHARED"].remove("/dev/shm")
        project = render_compose(self.compose, variables, "compose", ACTIVE_RUNNERS)
        self.assertEqual(
            self.project_findings(project, variables=variables),
            ["the spawner closes /var/tmp:/dev/mqueue only"],
        )

    def test_the_sandbox_paths_are_the_mounts_of_the_provision_runner(self):
        for name, volume in (
            ("SEMAPHORE_SANDBOX_ROOT", "semaphore_provision_sandboxes"),
            ("SEMAPHORE_SANDBOX_TMP", "semaphore_runner_tmp"),
        ):
            with self.subTest(name):
                source = f"lookup('volume', application_id, '{volume}').target"
                self.assertIn(source, self.variables[name])

    def test_the_sandbox_uids_are_disjoint_from_every_runner_uid(self):
        self.assertEqual(uid_range_findings(self.variables, self.volumes), [])

    def test_negative_control_an_overlapping_sandbox_base(self):
        variables = {**self.variables, "SEMAPHORE_SANDBOX_UID_BASE": 64100}
        self.assertEqual(
            uid_range_findings(variables, self.volumes),
            [
                "the sandbox uids hold the runner uid",
                "the sandbox uids reach the workspace runner uids",
                "the sandbox uids hold the broker uid",
            ],
        )

    def test_negative_control_a_broker_running_as_the_runner(self):
        volumes = copy.deepcopy(self.volumes)
        volumes[BROKER_VOLUME]["uid"] = volumes[TOKEN_VOLUME]["uid"]
        self.assertEqual(
            uid_range_findings(self.variables, volumes),
            ["the broker uid is root, the runner's or a workspace runner's"],
        )

    def test_negative_control_a_broker_login_the_runner_reads(self):
        volumes = copy.deepcopy(self.volumes)
        runner = volumes["semaphore_provision_runner_token"]["uid"]
        volumes[BROKER_VOLUME]["uid"] = runner
        self.assertEqual(
            runner_volume_findings(volumes, platform_runners(self.variables)),
            [f"{BROKER_VOLUME} is no 0400 secret of a uid beside the runner's"],
        )


if __name__ == "__main__":
    unittest.main()
