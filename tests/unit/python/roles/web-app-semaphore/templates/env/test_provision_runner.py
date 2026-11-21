from __future__ import annotations

import copy
import importlib
import re
import unittest
from collections.abc import Mapping

from ansible.plugins.filter.core import FilterModule as CoreFilters
from jinja2 import (
    DictLoader,
    Environment,
    StrictUndefined,
    UndefinedError,
    select_autoescape,
)
from jinja2.runtime import Context, missing

from plugins.lookup.volume import LookupModule as VolumeLookup
from utils.cache.applications import get_application_defaults
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_VOLUMES, ROLE_FILE_VARS_MAIN

FAKES = importlib.import_module("...files.provision._fake_provision", __package__)
hardening = FAKES.load("provision.hardening")
APPLICATION = "web-app-semaphore"
ROLE = PROJECT_ROOT / "roles" / APPLICATION
TEMPLATE = f"roles/{APPLICATION}/templates/env/provision-runner.j2"
RUNNER_TEMPLATE = f"roles/{APPLICATION}/templates/env/task-runner.j2"
GROUP_TLS = PROJECT_ROOT / "group_vars" / "all" / "02_tls.yml"
SERVICE = "provision-runner"
ENABLED = f"services.{SERVICE}.enabled"
INVENTORY = {"application_id": APPLICATION}
OPENBAO = "web-app-openbao"
DOMAIN = "infinito.example"
EXPRESSION = re.compile(r"\{\{(.*)\}\}", re.DOTALL)
VARIABLES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_VARS_MAIN)))
VOLUMES = load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_VOLUMES)))
DECLARED = frozenset(get_application_defaults(roles_dir=PROJECT_ROOT / "roles"))


def deploy_config(provisioning):
    """Args:
        provisioning: whether the deploy runs the provision runner.

    Returns:
        ``{path: value}`` of every ``config`` setting of the role such a
        deploy sets; a deploy without provisioning sets none of the runner
        but its flag.
    """
    if not provisioning:
        return {ENABLED: False, "services.semaphore": {"deploy": {}}}
    return {ENABLED: True, "services.semaphore": {"deploy": {}, "workspaces": {}}}


class DeployError(Exception):
    pass


class LazyContext(Context):
    def resolve_or_missing(self, key):
        found = super().resolve_or_missing(key)
        if found is missing and key in self.environment.sources:
            return self.environment.value(self.environment.sources[key])
        return found


class LazyMapping(Mapping):
    """Args:
    environment: the :class:`RoleEnvironment` that renders each value on
        access, as Ansible renders the values of a variable's dict.
    raw: the dict as the role declares it.
    """

    def __init__(self, environment, raw):
        self.environment = environment
        self.raw = raw

    def __getitem__(self, key):
        return self.environment.value(self.raw[key])

    def __iter__(self):
        return iter(self.raw)

    def __len__(self):
        return len(self.raw)


class RoleEnvironment(Environment):
    """Args:
    templates: ``{name: source}`` the loader serves.
    sources: ``{variable: raw value}`` of the role and the inventory, each
        rendered when a template first names it.
    config: :func:`deploy_config` the ``config`` lookup answers from.
    declared: the applications the ``domain`` lookup resolves, every one a
        role declares, as the real one maps the defaults of every role
        whatever the inventory holds and fails on any other name.
    """

    context_class = LazyContext

    def __init__(self, templates, sources, config, declared):
        super().__init__(
            loader=DictLoader(templates),
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
            trim_blocks=True,
        )
        self.sources = sources
        self.config = config
        self.declared = declared
        self.filters.update(CoreFilters().filters())
        self.globals["lookup"] = self.lookup

    def value(self, raw):
        if isinstance(raw, Mapping):
            return LazyMapping(self, raw)
        if isinstance(raw, list):
            return [self.value(item) for item in raw]
        if not isinstance(raw, str) or "{" not in raw:
            return raw
        expression = EXPRESSION.fullmatch(raw.strip())
        if expression and "}}" not in expression.group(1):
            return self.compile_expression(expression.group(1))()
        return self.from_string(raw).render()

    def lookup(self, name, *terms, **_options):
        if name == "volume":
            return VolumeLookup().run(list(terms))[0]
        if name == "config":
            if terms[1] not in self.config:
                raise DeployError(f"{terms[1]}, which the deploy does not set")
            return self.config[terms[1]]
        if name == "domain":
            if terms[0] not in self.declared:
                raise DeployError(f"{terms[0]}, which no role declares")
            return f"{terms[0]}.{DOMAIN}"
        if name == "tls" and terms[1:] == ("url.origin",):
            return f"https://{terms[0]}"
        raise DeployError(f"lookup('{name}'), which the test does not model")


def rendered(source, variables, provisioning):
    """Args:
        source: the text of ``templates/env/provision-runner.j2``, possibly
            planted.
        variables: the role's ``vars/main.yml``, possibly planted.
        provisioning: see :func:`deploy_config`.

    Returns:
        ``{name: value}`` of the env file ``sys-svc-compose`` renders on
        every deploy of the role, from the role's own variables, the TLS
        group variables and the lookups of the deploy; the env of the other
        runners it includes is left out, as it renders for the task runner
        on every deploy anyway.
    """
    sources = load_yaml_str(read_text(str(GROUP_TLS))) | variables | INVENTORY
    environment = RoleEnvironment(
        {TEMPLATE: source, RUNNER_TEMPLATE: ""},
        sources,
        deploy_config(provisioning),
        DECLARED,
    )
    text = environment.get_template(TEMPLATE).render()
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def mount_target(volume):
    (mount,) = [m for m in VOLUMES[volume]["mounts"] if m["service"] == SERVICE]
    return str(mount["target"])


def render_findings(source, variables, provisioning):
    """Args:
        source: see :func:`rendered`.
        variables: see :func:`rendered`.
        provisioning: see :func:`deploy_config`.

    Returns:
        Why the deploy fails on the env file, or, with provisioning, why the
        spawner would refuse it or serve another layout than the provision
        runner mounts; without it no spawner reads the file.
    """
    try:
        env = rendered(source, variables, provisioning)
    except UndefinedError as error:
        return [f"the env names {error.message}"]
    except DeployError as error:
        return [f"the env reads {error.args[0]}"]
    if not provisioning:
        return []
    try:
        container = hardening.layout(env)
    except SystemExit as refusal:
        return [f"the spawner refuses the env: {refusal}"]
    expected = {
        "runner": VOLUMES["semaphore_runner_token"]["uid"],
        "root": mount_target("semaphore_provision_sandboxes"),
        "tmp": mount_target("semaphore_runner_tmp"),
        "shared": variables["SEMAPHORE_SANDBOX_SHARED"],
        "tofu": variables["SEMAPHORE_SANDBOX_TOFU"],
        "ca": None,
        "bao": f"https://{OPENBAO}.{DOMAIN}",
    }
    served = {
        "runner": container["runner"],
        "root": str(container["root"]),
        "tmp": str(container["tmp"]),
        "shared": [str(path) for path in container["shared"]],
        "tofu": str(container["tofu"]),
        "ca": container["ca"],
        "bao": container["bao"],
    }
    return [
        f"the spawner serves {key} {served[key]!r}, not {expected[key]!r}"
        for key in expected
        if served[key] != expected[key]
    ]


class TestProvisionRunnerEnv(unittest.TestCase):
    def setUp(self):
        self.source = read_text(str(PROJECT_ROOT / TEMPLATE))

    def planted(self, old, new):
        self.assertIn(old, self.source)
        return self.source.replace(old, new)

    def off_beside_on(self, variables):
        """Args:
            variables: see :func:`rendered`.

        Returns:
            ``(off, on)``: the env with the provision runner off, and the env
            with it on whose ``SEMAPHORE_SANDBOX_BAO_ADDR`` is emptied, as
            the gate of the role empties it while the runner is off.
        """
        on = rendered(self.source, variables, True) | {hardening.BAO_ADDRESS: ""}
        return rendered(self.source, variables, False), on

    def test_the_env_renders_from_the_role_with_the_provision_runner_off(self):
        for provisioning in (False, True):
            with self.subTest(provisioning=provisioning):
                findings = render_findings(self.source, VARIABLES, provisioning)
                self.assertEqual(findings, [])
        off, on = self.off_beside_on(VARIABLES)
        self.assertEqual(off, on)

    def test_negative_control_an_ungated_bao_address_pins_openbao_with_the_runner_off(
        self,
    ):
        variables = copy.deepcopy(VARIABLES)
        self.assertIn(ENABLED, variables[hardening.BAO_ADDRESS])
        variables[hardening.BAO_ADDRESS] = (
            "{{ SEMAPHORE_WORKSPACES_VARIABLES.BAO_ADDR }}"
        )
        off, on = self.off_beside_on(variables)
        self.assertEqual(off[hardening.BAO_ADDRESS], f"https://{OPENBAO}.{DOMAIN}")
        self.assertNotEqual(off, on)

    def test_negative_control_a_broken_bao_address_fails_the_deploy(self):
        variables = copy.deepcopy(VARIABLES)
        workspaces = variables["SEMAPHORE_WORKSPACES_VARIABLES"]
        self.assertIn(f"'{OPENBAO}'", workspaces["BAO_ADDR"])
        workspaces["BAO_ADDR"] = workspaces["BAO_ADDR"].replace(
            f"'{OPENBAO}'", "'web-app-openbo'"
        )
        self.assertEqual(
            render_findings(self.source, variables, True),
            ["the env reads web-app-openbo, which no role declares"],
        )

    def test_negative_control_a_name_the_role_never_sets_is_found(self):
        planted = self.planted(
            "{{ SEMAPHORE_SANDBOX_TOFU }}", "{{ SEMAPHORE_SANDBOX_TOFU_PATH }}"
        )
        self.assertEqual(
            render_findings(planted, VARIABLES, False),
            ["the env names 'SEMAPHORE_SANDBOX_TOFU_PATH' is undefined"],
        )

    def test_negative_control_a_setting_of_the_runner_alone_fails_the_deploy(self):
        variables = copy.deepcopy(VARIABLES)
        variables["SEMAPHORE_SANDBOX_TOFU"] = (
            f"{{{{ lookup('config', application_id, 'services.{SERVICE}.tofu') }}}}"
        )
        self.assertEqual(
            render_findings(self.source, variables, False),
            [f"the env reads services.{SERVICE}.tofu, which the deploy does not set"],
        )

    def test_negative_control_a_range_holding_the_runner_is_refused(self):
        variables = copy.deepcopy(VARIABLES)
        variables["SEMAPHORE_SANDBOX_UID_BASE"] = 64000
        refusal = "sandbox/spawner.py:the sandbox uids hold root or the runner"
        self.assertEqual(
            render_findings(self.source, variables, True),
            [f"the spawner refuses the env: {refusal}"],
        )


if __name__ == "__main__":
    unittest.main()
