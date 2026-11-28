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
import unittest.mock as mock

from ansible.errors import AnsibleError, AnsibleFilterError
from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar

from plugins.filter.docker.build_digest import docker_build_digest
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import dump_yaml_str, load_yaml_str
from utils.github.variant.pools import ARCHITECTURES
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from ._fake_opentofu_build import FLAVORS, OPENTOFU, Build, roots

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
RUNNER = load_yaml_str(read_text(str(ROLE_DIR / ROLE_FILE_META_SERVICES)))[
    "task-runner"
]
PINS = tuple(
    f"{tool}_{key}"
    for tool in ("opentofu", "age", "keepassxc")
    for key in (
        "version",
        *(f"{kind}_{arch}" for kind in ("url", "sha256") for arch in ARCHITECTURES),
    )
)
HOST_ARCHITECTURE_BY_KERNEL = load_yaml_str(
    read_text(str(PROJECT_ROOT / "group_vars" / "all" / "00_general.yml"))
)["HOST_ARCHITECTURE_BY_KERNEL"]
STACK_HOST = "stack-host"
BUILD = ROLE_DIR / "files" / "shell" / "opentofu" / "build.sh"
EXPORT_TOOLS = {
    "age": {
        "arg": "SEMAPHORE_AGE",
        "url": "https://github.com/FiloSottile/age/releases/download/v{version}/age-v{version}-linux-amd64.tar.gz",
        "add": "ADD ${SEMAPHORE_AGE_URL} /age.tar.gz",
        "install": 'install /tmp/export-tools/age.tar.gz "${SEMAPHORE_AGE_SHA256}" /usr/local/bin/age',
    },
    "keepassxc": {
        "arg": "SEMAPHORE_KEEPASSXC",
        "url": "https://github.com/keepassxreboot/keepassxc/releases/download/{version}/KeePassXC-{version}-x86_64.AppImage",
        "add": "ADD ${SEMAPHORE_KEEPASSXC_URL} /keepassxc.AppImage",
        "install": 'install /tmp/export-tools/keepassxc.AppImage "${SEMAPHORE_KEEPASSXC_SHA256}" /usr/local/bin/keepassxc-cli',
    },
}
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
SANDBOX_ARG = "ARG SEMAPHORE_SANDBOX_ENTRYPOINT\n"
SANDBOX_STEPS = (
    SANDBOX_ARG.strip(),
    "command -v setpriv",
    'test -f "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/python/sandbox/spawner.py"',
    "files/python/sandbox/spawner.py serve /usr/local/bin/semaphore runner start",
    '> "${SEMAPHORE_SANDBOX_ENTRYPOINT}"',
    'chmod 0755 "${SEMAPHORE_SANDBOX_ENTRYPOINT}"',
)


def entry_point_findings(dockerfile: str) -> list[str]:
    """Args:
        dockerfile: the runner's Dockerfile, possibly planted.

    Returns:
        Every step of the sandbox entry point of 135 the image lacks; each
        runs in one ``&&`` chain, so a base image without ``setpriv`` or a
        checkout without the spawner fails the build.
    """
    return [
        f"the Dockerfile lacks {step}"
        for step in SANDBOX_STEPS
        if step not in dockerfile
    ]


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
    machine="x86_64",
    names=NAMES,
) -> dict:
    """Resolve the runner variables of one deploy.

    Args:
        machine: ``ansible_facts.architecture`` of the stack host that builds
            the runner image.
        names: the variables to resolve.
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
        ``{name: value}`` for every name in ``names``.
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
        **{f"services.task-runner.{key}": RUNNER[key] for key in PINS if key in RUNNER},
    }
    stubs = {
        "config": _Stub(lambda _app, path: config[path]),
        "path_absolute": _Stub(lambda *parts: "/".join(parts)),
        "file": _Stub(lambda *paths: [texts[path] for path in paths], many=True),
        "fileglob": _Stub(
            lambda *_patterns: sorted(p for p in texts if p.startswith(SCRIPTS_DIR)),
            many=True,
        ),
        "volume": _Stub(
            lambda _app, name: {"uid": uid, "gid": 1001, "target": f"/volumes/{name}"}
        ),
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
        "HOST_ARCHITECTURE_BY_KERNEL": HOST_ARCHITECTURE_BY_KERNEL,
        "STACK_HOST": STACK_HOST,
        "hostvars": {STACK_HOST: {"ansible_facts": {"architecture": machine}}},
    }
    declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
    templar = Templar(loader=DataLoader(), variables={**declared, **facts})
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return {name: templar.template(declared[name]) for name in names}


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

    def test_the_prune_keeps_workspace_runner_images(self) -> None:
        workspace_runner = (
            "semaphore_custom:ws-0b6f1c2e-3d4a-4b5c-8d6e-7f8091a2b3c4-v17.0.0"
        )
        workspace_base = f"{SOFTWARE_IMAGE}:v17.0.0"
        unused_base = f"{SOFTWARE_IMAGE}:v16.0.0"
        own = resolve(
            primary=[ROLE],
            tag=NEW,
            listed=(*self.LISTED, workspace_runner, workspace_base, unused_base),
        )
        pruned = own["SEMAPHORE_RUNNER_PRUNED_IMAGES"]
        self.assertNotIn(workspace_runner, pruned)
        self.assertNotIn(workspace_base, pruned)
        self.assertIn(unused_base, pruned)

    def test_the_prune_keeps_a_workspace_runner_on_an_own_build(self) -> None:
        workspace_runner = (
            "semaphore_custom:ws-0b6f1c2e-3d4a-4b5c-8d6e-7f8091a2b3c4-dev-older"
        )
        workspace_base = f"{SOFTWARE_IMAGE}:dev-older"
        own = resolve(
            primary=[ROLE],
            tag=NEW,
            listed=(*self.LISTED, workspace_runner, workspace_base),
        )
        pruned = own["SEMAPHORE_RUNNER_PRUNED_IMAGES"]
        self.assertNotIn(workspace_runner, pruned)
        self.assertNotIn(workspace_base, pruned)

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

    def test_the_runner_image_carries_the_sandbox_entry_point(self) -> None:
        self.assertEqual(entry_point_findings(self.dockerfile), [])
        entry = load_yaml_str(read_text(str(VARS)))["SEMAPHORE_SANDBOX_ENTRYPOINT"]
        self.assertEqual(
            self.first["SEMAPHORE_RUNNER_BUILD_ARGS"]["SEMAPHORE_SANDBOX_ENTRYPOINT"],
            entry,
        )

    def test_negative_control_an_image_without_the_sandbox_entry_point(self) -> None:
        start = self.dockerfile.index(SANDBOX_ARG)
        end = self.dockerfile.index("\n\n", start)
        planted = self.dockerfile[:start] + self.dockerfile[end + 2 :]
        self.assertEqual(
            entry_point_findings(planted),
            [f"the Dockerfile lacks {step}" for step in SANDBOX_STEPS],
        )


class TestOpenTofuLayer(unittest.TestCase):
    def setUp(self) -> None:
        self.dockerfile = read_text(str(DOCKERFILE))
        self.build = Build(RUNNER["opentofu_version"])
        self.addCleanup(self.build.close)

    def built(self):
        mirrored = self.build.run("mirror", str(self.build.opentofu), "linux_amd64")
        self.assertEqual(mirrored.returncode, 0, mirrored.stderr)
        mirror_calls = self.build.calls()
        validated = self.build.run("validate", str(self.build.opentofu))
        return mirror_calls, validated

    def test_the_build_pins_and_verifies_opentofu(self) -> None:
        version = tuple(int(part) for part in RUNNER["opentofu_version"].split("."))
        self.assertGreaterEqual(version, (1, 10, 0))
        args = resolve(primary=[ROLE], tag=OLD)["SEMAPHORE_RUNNER_BUILD_ARGS"]
        self.assertEqual(
            args["SEMAPHORE_OPENTOFU_URL"],
            RUNNER["opentofu_url_amd64"].replace(
                "{version}", RUNNER["opentofu_version"]
            ),
        )
        self.assertRegex(args["SEMAPHORE_OPENTOFU_SHA256"], r"^[0-9a-f]{64}$")
        self.assertEqual(self.dockerfile.count("ADD "), 1 + len(EXPORT_TOOLS))
        self.assertIn(
            "ADD ${SEMAPHORE_OPENTOFU_URL} /tmp/opentofu.tar.gz", self.dockerfile
        )
        self.assertIn(
            'install /tmp/opentofu.tar.gz "${SEMAPHORE_OPENTOFU_SHA256}" /usr/local/bin/tofu',
            self.dockerfile,
        )
        archive, digest = self.build.archive("#!/bin/sh\necho OpenTofu v1.13.9\n")
        binary = self.build.prefix() / "bin" / "tofu"
        for wrong in ("0" * 64, digest[:-1], "not-a-sum"):
            with self.subTest(sum=wrong):
                result = self.build.run("install", str(archive), wrong, str(binary))
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(binary.exists())
        result = self.build.run("install", str(archive), digest, str(binary))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OpenTofu v1.13.9", result.stdout)

    def test_the_build_initialises_every_root_offline(self) -> None:
        self.assertRegex(
            self.dockerfile,
            r"FROM opentofu AS opentofu-check\n\nRUN --network=none bash \S+/build\.sh\" "
            r"\\\n\s+validate ",
        )
        self.assertIn(
            "COPY --from=opentofu-check /usr/local/share/opentofu/validated",
            self.dockerfile,
        )
        mirror_calls, validated = self.built()
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertTrue(all(call["cli_config"] is None for call in mirror_calls))
        inits = [c for c in self.build.calls() if c["argv"][0] == "init"]
        self.assertEqual(len(inits), len(roots()) * len(FLAVORS))
        for call in self.build.calls():
            self.assertEqual(call["cli_config"], str(self.build.opentofu / "tofurc"))
        for call in inits:
            self.assertIn("-backend=false", call["argv"])
            self.assertIn("-lockfile=readonly", call["argv"])

    def test_the_mirror_installs_the_module_tree_of_every_root_first(self) -> None:
        mirror_calls, _ = self.built()
        steps = [call["argv"][:2] for call in mirror_calls]
        pair = [["get"], ["providers", "mirror"]]
        self.assertEqual(steps, pair * len(roots()) * len(FLAVORS))
        for get, mirror in zip(mirror_calls[::2], mirror_calls[1::2], strict=True):
            self.assertEqual(get["main"], mirror["main"])
            self.assertIsNone(get["cli_config"])

    def test_the_lock_installs_the_module_tree_first(self) -> None:
        root = self.build.opentofu / "roots" / "hetzner"
        result = self.build.run(
            "lock", str(self.build.opentofu), str(root), "linux_amd64"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        steps = [call["argv"][:2] for call in self.build.calls()]
        self.assertEqual(steps, [["get"], ["providers", "lock"]])

    def test_negative_control_a_mirror_without_the_module_tree_fails(self) -> None:
        script = read_text(str(BUILD))
        step = '  install_modules "$1"\n'
        self.assertEqual(script.count(step), 1)
        unfixed = self.build.directory / "build.sh"
        unfixed.write_text(script.replace(step, ""), encoding="utf-8")
        self.build.script = unfixed
        result = self.build.run("mirror", str(self.build.opentofu), "linux_amd64")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Module not installed", result.stderr)

    def test_the_cli_config_installs_from_the_mirror_only(self) -> None:
        tofurc = read_text(str(OPENTOFU / "tofurc"))
        blocks = re.findall(r"^\s*(\w+)\s*\{", tofurc, re.MULTILINE)
        self.assertEqual(blocks, ["provider_installation", "filesystem_mirror"])
        path = re.search(r'path\s*=\s*"([^"]+)"', tofurc).group(1)
        self.assertIn(f"COPY --from=opentofu {path} {path}\n", self.dockerfile)

    def test_a_provider_missing_from_the_mirror_fails_the_build(self) -> None:
        _, validated = self.built()
        self.assertEqual(validated.returncode, 0, validated.stderr)
        lock = self.build.opentofu / "roots" / "hetzner" / ".terraform.lock.hcl"
        with lock.open("a", encoding="utf-8") as handle:
            handle.write('\nprovider "registry.opentofu.org/example/absent" {\n}\n')
        result = self.build.run("validate", str(self.build.opentofu))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("example/absent is not in the mirror", result.stderr)

    def test_the_build_validates_every_root_with_each_dns_flavor(self) -> None:
        _, validated = self.built()
        self.assertEqual(validated.returncode, 0, validated.stderr)
        modules = OPENTOFU / "modules"
        dns = {
            read_text(str(modules / f"dns-{flavor}" / "main.tf.json")): flavor
            for flavor in FLAVORS
        }
        names = roots()
        seen = []
        for call in self.build.calls():
            if call["argv"][0] != "validate":
                continue
            flavor = dns[call["dns"]]
            seen.append((names[call["main"]], flavor))
            self.assertEqual(json.loads(call["catalog"]), {})
            zone_id = json.loads(call["workspace"])["dns"]["zone_id"]
            self.assertEqual(zone_id == "", flavor == "knot")
        expected = sorted(
            (root, flavor) for root in names.values() for flavor in FLAVORS
        )
        self.assertEqual(sorted(seen), expected)
        self.assertEqual(len(validated.stdout.splitlines()), len(expected))

    def test_the_build_stages_every_file_a_dns_module_reads(self) -> None:
        dns = read_text(str(OPENTOFU / "modules" / "dns-cloudflare" / "main.tf.json"))
        self.assertIn('file(\\"${path.module}/broker.json\\")', dns)
        _, validated = self.built()
        self.assertEqual(validated.returncode, 0, validated.stderr)

    def test_negative_control_a_build_without_the_broker_stand_in_fails(self) -> None:
        script = read_text(str(BUILD))
        step = '"${target}/modules/dns/broker.json"\n'
        self.assertEqual(script.count(step), 1)
        unfixed = self.build.directory / "build.sh"
        unfixed.write_text(
            script.replace(step, '"${target}/unstaged.json"\n'), encoding="utf-8"
        )
        self.build.script = unfixed
        _, validated = self.built()
        self.assertNotEqual(validated.returncode, 0)
        self.assertIn('no file exists at "modules/dns/broker.json"', validated.stderr)


class TestExportTools(unittest.TestCase):
    def setUp(self) -> None:
        self.dockerfile = read_text(str(DOCKERFILE))
        self.build = Build(RUNNER["opentofu_version"])
        self.addCleanup(self.build.close)

    def releases(self):
        """Returns:
        ``{tool: (archive, sha256, binary, version line)}`` of release-shaped fakes.
        """
        prefix = self.build.prefix()
        age, age_sum = self.build.archive("#!/bin/sh\necho v1.3.2\n", "age/age")
        kpx, kpx_sum = self.build.appimage("keepassxc-cli", "#!/bin/sh\necho 2.8.0\n")
        return {
            "age": (age, age_sum, prefix / "bin" / "age", "v1.3.2"),
            "keepassxc": (kpx, kpx_sum, prefix / "bin" / "keepassxc-cli", "2.8.0"),
        }

    def assert_sum_gates_the_install(self) -> None:
        for tool, (archive, digest, binary, line) in self.releases().items():
            for wrong in ("0" * 64, digest[:-1], "not-a-sum"):
                result = self.build.run("install", str(archive), wrong, str(binary))
                self.assertNotEqual(result.returncode, 0, f"{tool} took {wrong}")
                self.assertFalse(binary.is_symlink() or binary.exists(), tool)
            result = self.build.run("install", str(archive), digest, str(binary))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(line, result.stdout)

    def test_the_build_pins_keepassxc_and_age(self) -> None:
        args = resolve(primary=[ROLE], tag=OLD)["SEMAPHORE_RUNNER_BUILD_ARGS"]
        self.assertIn("linux_amd64", RUNNER["opentofu_url_amd64"])
        for tool, pin in EXPORT_TOOLS.items():
            with self.subTest(tool=tool):
                version = RUNNER[f"{tool}_version"]
                self.assertRegex(version, r"^[0-9]+\.[0-9]+\.[0-9]+$")
                self.assertEqual(RUNNER[f"{tool}_url_amd64"], pin["url"])
                self.assertEqual(
                    args[f"{pin['arg']}_URL"], pin["url"].replace("{version}", version)
                )
                self.assertRegex(args[f"{pin['arg']}_SHA256"], r"^[0-9a-f]{64}$")
                self.assertEqual(
                    args[f"{pin['arg']}_SHA256"], RUNNER[f"{tool}_sha256_amd64"]
                )
                self.assertIn(pin["add"], self.dockerfile)
                self.assertIn(pin["install"], self.dockerfile)
        self.assertRegex(
            self.dockerfile,
            r"FROM scratch AS export-tools\n(?:.*\n)*?RUN --mount=type=bind,"
            r"from=export-tools,target=/tmp/export-tools \\\n\s+bash \S+/build\.sh\" "
            r"runtime \\\n",
        )
        self.assert_sum_gates_the_install()

    def test_the_appimage_lands_beside_its_binary(self) -> None:
        archive, digest, binary, _ = self.releases()["keepassxc"]
        result = self.build.run("install", str(archive), digest, str(binary))
        self.assertEqual(result.returncode, 0, result.stderr)
        appdir = binary.parent.parent / "lib" / "keepassxc-cli"
        self.assertEqual(binary.resolve(), appdir / "usr" / "bin" / "keepassxc-cli")

    def test_negative_control_a_missing_sum_fails_the_build_arguments(self) -> None:
        for key in (
            "age_sha256_amd64",
            "keepassxc_sha256_amd64",
            "age_url_amd64",
            "keepassxc_version",
        ):
            with self.subTest(key=key), mock.patch.dict(RUNNER):
                del RUNNER[key]
                with self.assertRaises(AnsibleError):
                    resolve(primary=[ROLE], tag=OLD)

    def test_negative_control_an_installer_without_the_sum_check_installs(
        self,
    ) -> None:
        text = read_text(str(BUILD))
        check = "| sha256sum --check --strict --quiet -\n"
        self.assertIn(check, text)
        planted = self.build.directory / "build.sh"
        planted.write_text(text.replace(check, "| cat >/dev/null\n"), encoding="utf-8")
        self.build.script = planted
        archive, _digest = self.build.archive("#!/bin/sh\necho v1.3.2\n", "age/age")
        binary = self.build.prefix() / "bin" / "age"
        result = self.build.run("install", str(archive), "0" * 64, str(binary))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(binary.is_file())


if __name__ == "__main__":
    unittest.main()
