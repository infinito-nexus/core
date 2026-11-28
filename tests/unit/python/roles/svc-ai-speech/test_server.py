"""What the whisper.cpp server of svc-ai-speech is started with.

The server reads only WAV unless it converts the upload first, so a Talk
recording, a WebM with a video track, needs ``--convert``. Its language
defaults to English, and ``--detect-language`` only reports the language
instead of transcribing, so a German call needs ``--language auto``. It routes
one inference path, which has to be the OpenAI route Nextcloud's
``integration_openai`` appends to its STT URL. The model comes from the pinned
model store, read-only, and a model whose name ends in ``.en`` would force
every call into English.
"""

from __future__ import annotations

import ipaddress
import math
import re
import unittest
from pathlib import Path
from typing import ClassVar

from ansible.plugins.filter.core import FilterModule
from jinja2 import DictLoader, Environment, StrictUndefined, select_autoescape
from jinja2.nativetypes import NativeEnvironment

from plugins.filter.docker.architecture_tag import docker_architecture_tag
from plugins.filter.resource_filter import resolve_cpus
from plugins.lookup.cache_artefacts import LookupModule as CacheArtefacts
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml, load_yaml_str
from utils.docker.image.architecture_tags import architecture_tags
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLE = "svc-ai-speech"
SERVICE = "speech"
PIPER = "piper"
ROLE_DIR = Path(PROJECT_ROOT) / "roles" / ROLE
STORE = "/srv/cache/models"
INSTANCE_DIR = "/srv/docker/speech"
HOST_CPUS = 16
COMPOSE_BASE = "roles/sys-svc-compose/templates/base.yml.j2"
CONTAINER_BASE = "roles/sys-svc-container/templates/base.yml.j2"
BUILD_BLOCK = "build:\n  context: .\n  dockerfile: Dockerfile"
IMAGE = "ghcr.io/ggml-org/whisper.cpp"
CPU_IMAGE_TAG = re.compile(r"main-[0-9a-f]{40}")
ENGLISH_ONLY = re.compile(r"\.en[.-]")
COMMIT = re.compile(r"[0-9a-f]{40}")
PINNED_REQUIREMENT = re.compile(r"[A-Za-z0-9._-]+==[0-9][A-Za-z0-9.]*")
WHEEL_HASH = re.compile(r"--hash=sha256:[0-9a-f]{64}")
VOICE_CONFIG_SUFFIX = ".json"
REQUIREMENTS = ROLE_DIR / "files" / "python" / "requirements.txt"
DOCKERFILE = ROLE_DIR / "files" / "Dockerfile"
GENERAL_VARS = Path(PROJECT_ROOT) / "group_vars" / "all" / "00_general.yml"
STACK_HOST = "stack"
AMD64_KERNEL = "x86_64"
ARM64_KERNEL = "aarch64"
ARM64 = "arm64"


def _services() -> dict:
    return load_yaml(str(ROLE_DIR / ROLE_FILE_META_SERVICES))


def _entity() -> dict:
    return _services()[SERVICE]


def _piper() -> dict:
    return _services()[PIPER]


def _config(path: str):
    node = {"services": _services()}
    for part in path.split("."):
        node = node[part]
    return node


def _artefacts() -> dict:
    return CacheArtefacts().run([ROLE])[0]


def _lookup(name, *terms, **_kwargs):
    if terms[0] != ROLE:
        raise AssertionError(f"unexpected lookup {name} {terms}")
    if name == "config":
        return _config(terms[1])
    if name == "cpus":
        return float(resolve_cpus(_config(f"services.{terms[1]}.cpus"), HOST_CPUS))
    if name == "cache_artefacts":
        return _artefacts()
    if name == "container":
        return INSTANCE_DIR
    raise AssertionError(f"unexpected lookup {name} {terms}")


def _role_vars(kernel: str) -> dict:
    """Args:
        kernel: the ``architecture`` fact of the stack host.

    Returns:
        Every role variable as its native value, with the model store at
        ``STORE`` and the CPU cap resolved against ``HOST_CPUS`` cores.
    """
    env = NativeEnvironment(undefined=StrictUndefined)
    env.filters.update(FilterModule().filters())
    env.filters["entity_name"] = entity_name
    env.filters["docker_architecture_tag"] = docker_architecture_tag
    env.globals["lookup"] = _lookup
    values: dict = {
        "AI_MODELS_STORE_PATH": STORE,
        "HOST_ARCHITECTURE_BY_KERNEL": load_yaml(str(GENERAL_VARS))[
            "HOST_ARCHITECTURE_BY_KERNEL"
        ],
        "STACK_HOST": STACK_HOST,
        "hostvars": {STACK_HOST: {"ansible_facts": {"architecture": kernel}}},
    }
    for name, expression in load_yaml(str(ROLE_DIR / ROLE_FILE_VARS_MAIN)).items():
        values[name] = env.from_string(str(expression)).render(**values)
    return values


def _compose(role_vars: dict) -> tuple[dict, dict[str, list[dict]]]:
    """Args:
        role_vars: the rendered role variables.

    Returns:
        The parsed services keyed by name and, per service, the keyword
        arguments of every ``container_volumes`` and ``container_image`` call,
        keyed ``<service>`` and ``<service>:image``.
    """
    volume_calls: dict[str, list[dict]] = {}

    def _template_lookup(name, *terms, **kwargs):
        if name == "container_volumes":
            volume_calls.setdefault(terms[0], []).append(kwargs)
        if name == "container_image":
            volume_calls.setdefault(f"{terms[1]}:image", []).append(kwargs)
        if name == "template":
            return BUILD_BLOCK
        return ""

    env = Environment(
        loader=DictLoader(
            {
                "compose": read_text(str(ROLE_DIR / ROLE_FILE_TEMPL_COMPOSE)),
                COMPOSE_BASE: "services:\n",
                CONTAINER_BASE: "",
            }
        ),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.globals["lookup"] = _template_lookup
    rendered = env.get_template("compose").render(**role_vars)
    return load_yaml_str(rendered)["services"], volume_calls


def _option(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


def _unpinned(requirements: str) -> list[str]:
    """
    Args:
        requirements: a pip requirements file in ``--require-hashes`` form.

    Returns:
        The first token of every requirement that pins no exact version or
        carries no sha256 wheel hash.
    """
    logical = requirements.replace("\\\n", " ").splitlines()
    return [
        line.split()[0]
        for line in logical
        if line.strip()
        and not (
            PINNED_REQUIREMENT.fullmatch(line.split()[0]) and WHEEL_HASH.search(line)
        )
    ]


class ServiceCase(unittest.TestCase):
    name: ClassVar[str]
    role_vars: ClassVar[dict] = _role_vars(AMD64_KERNEL)
    service: ClassVar[dict]
    volume_calls: ClassVar[dict[str, list[dict]]]

    @classmethod
    def setUpClass(cls) -> None:
        services, cls.volume_calls = _compose(cls.role_vars)
        cls.service = services[cls.name]

    def assert_serves(self, entity: dict, route: str) -> None:
        command = self.service["command"]
        port = str(entity["ports"]["internal"]["http"])

        self.assertTrue(ipaddress.ip_address(_option(command, "--host")).is_unspecified)
        self.assertEqual(_option(command, "--port"), port)
        self.assertEqual(self.service["expose"], [port])
        self.assertEqual(_option(command, "--inference-path"), route)


class TestServer(ServiceCase):
    name = SERVICE

    def test_the_server_answers_the_openai_transcription_route(self) -> None:
        self.assertEqual(self.service["entrypoint"], ["whisper-server"])
        self.assert_serves(_entity(), "/v1/audio/transcriptions")

    def test_every_upload_is_converted_before_inference(self) -> None:
        command = self.service["command"]

        self.assertIn("--convert", command)
        self.assertEqual(_option(command, "--tmp-dir"), "/tmp")

    def test_the_language_is_detected_and_then_transcribed(self) -> None:
        command = self.service["command"]

        self.assertNotIn("--detect-language", command)
        self.assertNotIn("-dl", command)
        self.assertEqual(_option(command, "--language"), "auto")

    def test_the_model_comes_read_only_from_the_pinned_store(self) -> None:
        record = _artefacts()[_entity()["artefact"]]

        self.assertEqual(
            _option(self.service["command"], "--model"), f"{STORE}/{record['tree']}"
        )
        self.assertEqual(
            self.volume_calls[SERVICE], [{"extra_volumes": [f"{STORE}:{STORE}:ro"]}]
        )

    def test_the_pinned_model_is_multilingual(self) -> None:
        record = _artefacts()[_entity()["artefact"]]

        self.assertIsNone(ENGLISH_ONLY.search(record["upstream"].rsplit("/", 1)[1]))

    def test_threads_follow_the_cpu_cap(self) -> None:
        cpus = float(resolve_cpus(_entity()["cpus"], HOST_CPUS))

        self.assertEqual(
            _option(self.service["command"], "--threads"), str(math.ceil(cpus))
        )

    def test_the_health_probe_reads_the_ready_route(self) -> None:
        self.assertEqual(
            _entity()["healthcheck"], {"flavor": "http_status", "path": "health"}
        )

    def test_the_image_is_the_cpu_build_of_a_pinned_commit(self) -> None:
        self.assertEqual(_entity()["image"], IMAGE)
        self.assertIsNotNone(CPU_IMAGE_TAG.fullmatch(_entity()["version"]))

    def test_an_amd64_host_pulls_the_pinned_tag(self) -> None:
        self.assertEqual(
            self.volume_calls[f"{SERVICE}:image"], [{"version": _entity()["version"]}]
        )

    def test_an_arm64_host_pulls_the_arm64_build_of_the_pinned_commit(self) -> None:
        _services, calls = _compose(_role_vars(ARM64_KERNEL))
        commit = _entity()["version"].removeprefix("main-")

        self.assertEqual(
            calls[f"{SERVICE}:image"], [{"version": f"main-arm64-{commit}"}]
        )

    def test_the_arm64_tag_is_derived_from_the_one_version_pin(self) -> None:
        tags = architecture_tags(_entity()["version"], _entity()["architecture_tags"])

        self.assertEqual(set(tags), {ARM64})
        self.assertTrue(
            tags[ARM64].endswith(_entity()["version"].removeprefix("main-"))
        )
        self.assertNotIn(
            tags[ARM64], read_text(str(ROLE_DIR / ROLE_FILE_META_SERVICES))
        )

    def test_the_role_declares_no_architecture_narrowing(self) -> None:
        self.assertFalse(
            any(
                "architectures" in entry
                for entry in _services().values()
                if isinstance(entry, dict)
            )
        )


class TestSynthesisServer(ServiceCase):
    name = PIPER

    def test_the_server_answers_the_openai_speech_route(self) -> None:
        self.assert_serves(_piper(), "/v1/audio/speech")

    def test_the_voice_comes_read_only_from_the_pinned_store(self) -> None:
        records = _artefacts()
        voice = records[_piper()["artefact"]]
        trees = {record["tree"] for record in records.values()}
        command = self.service["command"]

        self.assertEqual(_option(command, "--model"), f"{STORE}/{voice['tree']}")
        self.assertEqual(
            _option(command, "--config"),
            f"{STORE}/{voice['tree']}{VOICE_CONFIG_SUFFIX}",
        )
        self.assertIn(f"{voice['tree']}{VOICE_CONFIG_SUFFIX}", trees)
        self.assertEqual(
            self.volume_calls[PIPER], [{"extra_volumes": [f"{STORE}:{STORE}:ro"]}]
        )

    def test_the_start_waits_for_every_voice_file_in_the_store(self) -> None:
        required = {record["name"] for record in self.role_vars["SPEECH_ARTEFACTS"]}

        self.assertEqual(required, set(_artefacts()))
        self.assertIn(_piper()["artefact"], required)
        self.assertIn(_piper()["artefact"] + VOICE_CONFIG_SUFFIX, required)

    def test_the_voice_is_pinned_at_a_commit(self) -> None:
        voice = _artefacts()[_piper()["artefact"]]

        self.assertIsNotNone(COMMIT.fullmatch(voice["revision"]))
        self.assertIn(f"/resolve/{voice['revision']}/", voice["upstream"])

    def test_the_request_follows_the_config(self) -> None:
        command = self.service["command"]

        self.assertEqual(_option(command, "--speaker"), str(_piper()["speaker"]))
        self.assertEqual(
            _option(command, "--max-input-chars"), str(_piper()["max_input_chars"])
        )
        self.assertEqual(
            _option(command, "--timeout"), str(_piper()["request_timeout"])
        )
        self.assertEqual(_option(command, "--tmp-dir"), "/tmp")

    def test_the_health_probe_has_the_transcription_server_shape(self) -> None:
        self.assertEqual(_piper()["healthcheck"], _entity()["healthcheck"])

    def test_the_image_is_built_from_hash_pinned_wheels(self) -> None:
        dockerfile = read_text(str(DOCKERFILE))

        self.assertTrue(_piper()["custom"])
        self.assertIn("build", self.service)
        self.assertIn("piper-tts==", read_text(str(REQUIREMENTS)))
        self.assertEqual(_unpinned(read_text(str(REQUIREMENTS))), [])
        self.assertIn("--require-hashes", dockerfile)
        self.assertIn("--only-binary=:all:", dockerfile)

    def test_an_unhashed_or_unpinned_requirement_is_caught(self) -> None:
        requirements = (
            "piper-tts==1.8.0\n"
            "onnxruntime>=1.31 \\\n"
            f"    --hash=sha256:{'0' * 64}\n"
            "numpy==2.5.4 \\\n"
            f"    --hash=sha256:{'0' * 64}\n"
        )

        self.assertEqual(
            _unpinned(requirements), ["piper-tts==1.8.0", "onnxruntime>=1.31"]
        )


if __name__ == "__main__":
    unittest.main()
