"""The Semaphore runner is rebuilt in Semaphore's own round and on changed inputs only.

A deploy that pulls Semaphore in as a provider of another application keeps the
runner the stack host deployed, so it builds neither the runner nor the
Infinito.Nexus base image of its own commit. The real ``vars/main.yml`` is
resolved by Ansible's templar with the real role filters, the stack-host facts
of ``tasks/utils/runner.yml`` and ``tasks/utils/runner/prune.yml`` faked and the
site lookups stubbed.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import re
import unittest
from unittest import mock

from ansible.errors import AnsibleFilterError
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from plugins.filter.docker.build_digest import docker_build_digest
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import dump_yaml_str
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = "web-app-semaphore"
ROLE_DIR = PROJECT_ROOT / "roles" / ROLE
VARS = ROLE_DIR / ROLE_FILE_VARS_MAIN
FILTERS = ROLE_DIR / "filter_plugins"
DOCKERFILE = ROLE_DIR / "files" / "runner" / "Dockerfile"

filter_loader.add_directory(str(PROJECT_ROOT / "plugins" / "filter"))
filter_loader.add_directory(str(FILTERS))

SOFTWARE_IMAGE = "slot/debian"
SERVER_IMAGE = "semaphoreui/semaphore"
SERVER_VERSION = "v2.19.17"
DOCKERFILE_PATH = f"roles/{ROLE}/files/runner/Dockerfile"
SCRIPTS_DIR = f"roles/{ROLE}/files/shell/repository"
DOCKERFILE_TEXT = "FROM ${SEMAPHORE_RUNNER_BASE_IMAGE}\n"
SCRIPTS = {"app-control.sh": "echo stop\n", "deploy.sh": "echo deploy\n"}
SKIPPED = {"changed": False, "skipped": True}
OLD, NEW = "dev-old", "dev-new"
OLD_BASE, NEW_BASE = f"{SOFTWARE_IMAGE}:{OLD}", f"{SOFTWARE_IMAGE}:{NEW}"
OLD_RUNNER, NEW_RUNNER = f"semaphore_custom:{OLD}", f"semaphore_custom:{NEW}"
DIGEST = "a" * 64
NAMES = (
    "SEMAPHORE_RUNNER_BUILD_ARGS",
    "SEMAPHORE_RUNNER_BASE_IMAGE",
    "SEMAPHORE_RUNNER_IMAGE_TAG",
    "SEMAPHORE_RUNNER_IMAGE",
    "SEMAPHORE_RUNNER_INPUTS_DIGEST",
    "SEMAPHORE_RUNNER_INPUTS_LABEL",
    "SEMAPHORE_RUNNER_INPUTS_FORMAT",
    "SEMAPHORE_RUNNER_LIST_FORMAT",
    "SEMAPHORE_RUNNER_PRUNE_FILTERS",
    "SEMAPHORE_RUNNER_PRUNED_IMAGES",
)


def _load_filters():
    path = FILTERS / "semaphore_runner.py"
    spec = importlib.util.spec_from_file_location("semaphore_runner", str(path))
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _Stub(LookupBase):
    def __init__(self, answer, *, many=False):
        super().__init__()
        self._answer = answer
        self._many = many

    def run(self, terms, variables=None, **kwargs):
        if self._many:
            return self._answer(*terms)
        return [self._answer(*terms, **kwargs)]


def resolve(
    *,
    primary,
    tag,
    compose=None,
    label=None,
    held=True,
    dockerfile=DOCKERFILE_TEXT,
    scripts=None,
    server_version=SERVER_VERSION,
    uid=1001,
    image_build=True,
    listed=(),
) -> dict:
    """Resolve the runner variables of one deploy.

    Args:
        primary: what ``lookup('deployment').primary`` answers.
        tag: ``SOFTWARE_IMAGE_TAG`` of the deploy.
        compose: text of the compose file the stack host deployed, None when
            it holds none.
        label: inputs label the deployed runner image carries, '' for none.
        held: whether the stack host still holds the deployed images, None
            when the check is skipped because no runner is deployed.
        dockerfile: text of the runner Dockerfile in the checkout.
        scripts: ``{name: text}`` of ``files/shell/repository``, ``SCRIPTS``
            when None.
        server_version: pinned version of the Semaphore server image.
        uid: UID the runner token volume declares for the runner user.
        image_build: ``SOFTWARE_IMAGE_BUILD`` of the deploy.
        listed: the image tags ``container image ls`` lists on the stack host.

    Returns:
        ``{name: value}`` for every name in ``NAMES``.
    """
    texts = {
        DOCKERFILE_PATH: dockerfile,
        **{
            f"{SCRIPTS_DIR}/{name}": text
            for name, text in (SCRIPTS if scripts is None else scripts).items()
        },
    }
    config = {
        "services.semaphore.image": SERVER_IMAGE,
        "services.semaphore.version": server_version,
        "services.task-runner.name": "semaphore-runner",
    }
    stubs = {
        "config": _Stub(lambda _app, path: config[path]),
        "path_absolute": _Stub(lambda *parts: "/".join(parts)),
        "file": _Stub(lambda *paths: [texts[path] for path in paths], many=True),
        "fileglob": _Stub(
            lambda _pattern: sorted(p for p in texts if p.startswith(SCRIPTS_DIR)),
            many=True,
        ),
        "volume": _Stub(lambda _app, _name: {"uid": uid, "gid": 1001}),
        "deployment": _Stub(lambda: {"primary": primary}),
        "image": _Stub(lambda _app, _service, version: f"semaphore_custom:{version}"),
    }
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name in stubs:
            return stubs[name]
        return real_get(name, *args, **kwargs)

    if compose is None or held is None:
        inspected = SKIPPED
    elif held:
        inspected = {"rc": 0, "stdout_lines": [json.dumps(label), json.dumps("")]}
    else:
        inspected = {"rc": 1, "stdout_lines": []}
    facts = {
        "SOFTWARE_IMAGE": SOFTWARE_IMAGE,
        "SOFTWARE_IMAGE_TAG": tag,
        "SOFTWARE_IMAGE_BUILD": image_build,
        "semaphore_runner_compose": (
            SKIPPED
            if compose is None
            else {"content": base64.b64encode(compose.encode()).decode()}
        ),
        "semaphore_runner_held": inspected,
        "semaphore_runner_images": {"stdout_lines": list(listed)},
    }
    declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
    templar = Templar(loader=DataLoader(), variables={**declared, **facts})
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return {name: templar.template(declared[name]) for name in NAMES}


def rendered(deploy: dict) -> str:
    """Return the compose file a deploy leaves on the stack host.

    Args:
        deploy: what ``resolve`` answered for that deploy.
    """
    runner = {
        "image": str(deploy["SEMAPHORE_RUNNER_IMAGE"]),
        "build": {
            "dockerfile": "Dockerfile",
            "args": {
                str(name): str(value)
                for name, value in deploy["SEMAPHORE_RUNNER_BUILD_ARGS"].items()
            },
        },
    }
    return dump_yaml_str(
        {"services": {"semaphore": {}, "task-runner": runner}}, sort_keys=True
    )


class TestDecision(unittest.TestCase):
    def setUp(self) -> None:
        self.base = _load_filters().semaphore_runner_base

    def test_a_provider_round_keeps_the_deployed_base(self) -> None:
        self.assertEqual(self.base(DIGEST, NEW_BASE, OLD_BASE, DIGEST, False), OLD_BASE)

    def test_the_own_round_builds_on_the_image_of_this_deploy(self) -> None:
        self.assertEqual(self.base(DIGEST, NEW_BASE, OLD_BASE, DIGEST, True), NEW_BASE)

    def test_a_changed_input_builds_on_the_image_of_this_deploy(self) -> None:
        self.assertEqual(
            self.base(DIGEST, NEW_BASE, OLD_BASE, "b" * 64, False), NEW_BASE
        )

    def test_an_unlabelled_runner_builds_on_the_image_of_this_deploy(self) -> None:
        self.assertEqual(self.base(DIGEST, NEW_BASE, OLD_BASE, "", False), NEW_BASE)

    def test_no_deployed_runner_builds_on_the_image_of_this_deploy(self) -> None:
        self.assertEqual(self.base(DIGEST, NEW_BASE, "", "", False), NEW_BASE)

    def test_an_empty_inputs_digest_fails(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            self.base("", NEW_BASE, OLD_BASE, "", False)

    def test_an_empty_deploy_base_fails(self) -> None:
        with self.assertRaises(AnsibleFilterError):
            self.base(DIGEST, "", OLD_BASE, DIGEST, False)


class TestDigest(unittest.TestCase):
    def setUp(self) -> None:
        self.digest = _load_filters().semaphore_runner_digest

    def test_text_and_numbers_agree(self) -> None:
        self.assertEqual(
            self.digest({"UID": 1001, "TMP": "/tmp/x"}),
            self.digest({"TMP": "/tmp/x", "UID": "1001"}),
        )

    def test_a_changed_value_changes_the_digest(self) -> None:
        self.assertNotEqual(self.digest({"UID": 1001}), self.digest({"UID": 1002}))


class TestRounds(unittest.TestCase):
    def setUp(self) -> None:
        self.first = resolve(primary=[ROLE], tag=OLD)
        self.compose = rendered(self.first)
        self.label = str(self.first["SEMAPHORE_RUNNER_INPUTS_DIGEST"])

    def provider(self, **overrides) -> dict:
        settings = {
            "primary": ["web-app-gitea"],
            "tag": NEW,
            "compose": self.compose,
            "label": self.label,
            **overrides,
        }
        return resolve(**settings)

    def test_the_first_deploy_builds_on_its_own_image(self) -> None:
        self.assertEqual(
            (
                self.first["SEMAPHORE_RUNNER_BASE_IMAGE"],
                self.first["SEMAPHORE_RUNNER_IMAGE"],
            ),
            (OLD_BASE, OLD_RUNNER),
        )

    def test_a_provider_round_keeps_the_runner(self) -> None:
        provider = self.provider()
        self.assertEqual(provider["SEMAPHORE_RUNNER_IMAGE_TAG"], OLD)
        self.assertEqual(rendered(provider), self.compose)

    def test_the_own_round_builds_on_its_own_image(self) -> None:
        own = self.provider(primary=[ROLE, "web-app-gitea"])
        self.assertEqual(
            (own["SEMAPHORE_RUNNER_BASE_IMAGE"], own["SEMAPHORE_RUNNER_IMAGE"]),
            (NEW_BASE, NEW_RUNNER),
        )

    def test_a_changed_dockerfile_rebuilds_in_a_provider_round(self) -> None:
        provider = self.provider(dockerfile=DOCKERFILE_TEXT + "USER 1001\n")
        self.assertEqual(provider["SEMAPHORE_RUNNER_IMAGE_TAG"], NEW)

    def test_a_changed_repository_script_rebuilds_in_a_provider_round(self) -> None:
        provider = self.provider(scripts={**SCRIPTS, "deploy.sh": "echo new\n"})
        self.assertEqual(provider["SEMAPHORE_RUNNER_IMAGE_TAG"], NEW)

    def test_a_new_repository_script_rebuilds_in_a_provider_round(self) -> None:
        provider = self.provider(scripts={**SCRIPTS, "extra.sh": "echo extra\n"})
        self.assertEqual(provider["SEMAPHORE_RUNNER_IMAGE_TAG"], NEW)

    def test_a_new_server_image_rebuilds_in_a_provider_round(self) -> None:
        provider = self.provider(server_version="v2.19.18")
        self.assertEqual(provider["SEMAPHORE_RUNNER_IMAGE_TAG"], NEW)

    def test_a_changed_build_argument_rebuilds_in_a_provider_round(self) -> None:
        provider = self.provider(uid=1002)
        self.assertEqual(provider["SEMAPHORE_RUNNER_IMAGE_TAG"], NEW)

    def test_a_changed_input_changes_the_build_section_under_one_tag(self) -> None:
        kept = docker_build_digest(self.compose)
        for name, changed in (
            ("dockerfile", {"dockerfile": DOCKERFILE_TEXT + "USER 1001\n"}),
            ("script", {"scripts": {**SCRIPTS, "deploy.sh": "echo new\n"}}),
            ("server image", {"server_version": "v2.19.18"}),
            ("build argument", {"uid": 1002}),
        ):
            with self.subTest(input=name):
                own = resolve(primary=[ROLE], tag=OLD, **changed)
                self.assertNotEqual(docker_build_digest(rendered(own)), kept)

    def test_lost_images_rebuild_in_a_provider_round(self) -> None:
        self.assertEqual(self.provider(held=False)["SEMAPHORE_RUNNER_IMAGE_TAG"], NEW)

    def test_an_unlabelled_runner_rebuilds_in_a_provider_round(self) -> None:
        self.assertEqual(self.provider(label="")["SEMAPHORE_RUNNER_IMAGE_TAG"], NEW)

    def test_a_runner_of_other_inputs_rebuilds_in_a_provider_round(self) -> None:
        provider = self.provider(label=DIGEST)
        self.assertEqual(provider["SEMAPHORE_RUNNER_IMAGE_TAG"], NEW)

    def test_a_compose_without_runner_rebuilds_in_a_provider_round(self) -> None:
        provider = self.provider(
            compose=dump_yaml_str({"services": {"semaphore": {}}}, sort_keys=True),
            held=None,
        )
        self.assertEqual(provider["SEMAPHORE_RUNNER_IMAGE_TAG"], NEW)

    def test_the_inputs_digest_is_a_build_argument(self) -> None:
        self.assertEqual(
            self.first["SEMAPHORE_RUNNER_BUILD_ARGS"]["SEMAPHORE_RUNNER_INPUTS_DIGEST"],
            self.label,
        )


class TestPrune(unittest.TestCase):
    LISTED = (OLD_RUNNER, NEW_RUNNER, OLD_BASE, NEW_BASE, f"{SOFTWARE_IMAGE}:dev-older")

    def test_the_own_round_untags_everything_but_its_pair(self) -> None:
        own = resolve(primary=[ROLE], tag=NEW, listed=self.LISTED)
        self.assertEqual(
            own["SEMAPHORE_RUNNER_PRUNE_FILTERS"],
            [
                "--filter=reference=semaphore_custom",
                f"--filter=reference={SOFTWARE_IMAGE}",
            ],
        )
        self.assertEqual(
            own["SEMAPHORE_RUNNER_PRUNED_IMAGES"],
            [OLD_RUNNER, OLD_BASE, f"{SOFTWARE_IMAGE}:dev-older"],
        )

    def test_a_kept_runner_keeps_its_pair(self) -> None:
        first = resolve(primary=[ROLE], tag=OLD)
        provider = resolve(
            primary=["web-app-gitea"],
            tag=NEW,
            compose=rendered(first),
            label=str(first["SEMAPHORE_RUNNER_INPUTS_DIGEST"]),
            listed=self.LISTED,
        )
        self.assertEqual(
            provider["SEMAPHORE_RUNNER_PRUNED_IMAGES"],
            [NEW_RUNNER, NEW_BASE, f"{SOFTWARE_IMAGE}:dev-older"],
        )

    def test_a_pulled_base_image_is_not_listed(self) -> None:
        own = resolve(primary=[ROLE], tag=NEW, image_build=False)
        self.assertEqual(
            own["SEMAPHORE_RUNNER_PRUNE_FILTERS"],
            ["--filter=reference=semaphore_custom"],
        )


class TestDockerfile(unittest.TestCase):
    def setUp(self) -> None:
        self.dockerfile = read_text(str(DOCKERFILE))
        self.first = resolve(primary=[ROLE], tag=OLD)

    def test_every_build_argument_is_declared(self) -> None:
        declared = set(re.findall(r"^ARG\s+(\w+)", self.dockerfile, re.MULTILINE))
        self.assertEqual(set(self.first["SEMAPHORE_RUNNER_BUILD_ARGS"]), declared)

    def test_the_inputs_digest_is_the_label_the_deploy_reads(self) -> None:
        label = self.first["SEMAPHORE_RUNNER_INPUTS_LABEL"]
        self.assertIn(f'{label}="${{SEMAPHORE_RUNNER_INPUTS_DIGEST}}"', self.dockerfile)
        self.assertEqual(
            self.first["SEMAPHORE_RUNNER_INPUTS_FORMAT"],
            f'{{{{ json (index .Config.Labels "{label}") }}}}',
        )

    def test_the_image_list_names_repository_and_tag(self) -> None:
        self.assertEqual(
            self.first["SEMAPHORE_RUNNER_LIST_FORMAT"], "{{.Repository}}:{{.Tag}}"
        )


if __name__ == "__main__":
    unittest.main()
