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

from plugins.filter.resource_filter import resolve_cpus
from plugins.lookup.cache_artefacts import LookupModule as CacheArtefacts
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml, load_yaml_str
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLE = "svc-ai-speech"
SERVICE = "speech"
ROLE_DIR = Path(PROJECT_ROOT) / "roles" / ROLE
STORE = "/srv/cache/models"
HOST_CPUS = 16
COMPOSE_BASE = "roles/sys-svc-compose/templates/base.yml.j2"
CONTAINER_BASE = "roles/sys-svc-container/templates/base.yml.j2"
IMAGE = "ghcr.io/ggml-org/whisper.cpp"
CPU_IMAGE_TAG = re.compile(r"main-[0-9a-f]{40}")
ENGLISH_ONLY = re.compile(r"\.en[.-]")


def _entity() -> dict:
    return load_yaml(str(ROLE_DIR / ROLE_FILE_META_SERVICES))[SERVICE]


def _config(path: str):
    node = {"services": {SERVICE: _entity()}}
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
    raise AssertionError(f"unexpected lookup {name} {terms}")


def _role_vars() -> dict:
    """Render vars/main.yml in file order, as the role sees it.

    Returns:
        Every role variable as its native value, with the model store at
        ``STORE`` and the CPU cap resolved against ``HOST_CPUS`` cores.
    """
    env = NativeEnvironment(undefined=StrictUndefined)
    env.filters.update(FilterModule().filters())
    env.filters["entity_name"] = entity_name
    env.globals["lookup"] = _lookup
    values: dict = {"AI_MODELS_STORE_PATH": STORE}
    for name, expression in load_yaml(str(ROLE_DIR / ROLE_FILE_VARS_MAIN)).items():
        values[name] = env.from_string(str(expression)).render(**values)
    return values


def _compose(role_vars: dict) -> tuple[dict, list[dict]]:
    """Render the compose template with the lookups it calls stubbed out.

    Args:
        role_vars: the rendered role variables.

    Returns:
        The parsed speech service and the keyword arguments of every
        ``container_volumes`` call.
    """
    volume_calls: list[dict] = []

    def _template_lookup(name, *_terms, **kwargs):
        if name == "container_volumes":
            volume_calls.append(kwargs)
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
    return load_yaml_str(rendered)["services"][SERVICE], volume_calls


def _option(command: list[str], flag: str) -> str:
    return command[command.index(flag) + 1]


class TestServer(unittest.TestCase):
    role_vars: ClassVar[dict] = _role_vars()
    service: ClassVar[dict]
    volume_calls: ClassVar[list[dict]]

    @classmethod
    def setUpClass(cls) -> None:
        cls.service, cls.volume_calls = _compose(cls.role_vars)

    def test_the_server_answers_the_openai_transcription_route(self) -> None:
        command = self.service["command"]
        port = str(_entity()["ports"]["internal"]["http"])

        self.assertEqual(self.service["entrypoint"], ["whisper-server"])
        self.assertTrue(ipaddress.ip_address(_option(command, "--host")).is_unspecified)
        self.assertEqual(_option(command, "--port"), port)
        self.assertEqual(self.service["expose"], [port])
        self.assertEqual(
            _option(command, "--inference-path"), "/v1/audio/transcriptions"
        )

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
        (record,) = _artefacts().values()

        self.assertEqual(
            _option(self.service["command"], "--model"), f"{STORE}/{record['tree']}"
        )
        self.assertEqual(
            self.volume_calls, [{"extra_volumes": [f"{STORE}:{STORE}:ro"]}]
        )

    def test_the_pinned_model_is_multilingual(self) -> None:
        (record,) = _artefacts().values()

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


if __name__ == "__main__":
    unittest.main()
