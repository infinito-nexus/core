from __future__ import annotations

import ast
import unittest

from ansible.plugins.filter.core import FilterModule
from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml
from utils.roles.entity.name import entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT
from .test_config_model_list import render

GATEWAY_ROLE = "svc-ai-litellm"
GATEWAY_DIR = PROJECT_ROOT / "roles" / GATEWAY_ROLE
SPEECH_ROLE = "svc-ai-speech"
SPEECH_KEY = "speech"
PIPER_KEY = "piper"
SPEECH_DIR = PROJECT_ROOT / "roles" / SPEECH_ROLE
AI_GROUP_VARS = PROJECT_ROOT / "group_vars" / "all" / "16_ai.yml"
PIPER_URL_VAR = "PIPER_BASE_LOCAL_URL"
TRANSCRIPTION_ENDPOINT = "audio/transcriptions"
TRANSCRIPTION_MODE = "audio_transcription"
SYNTHESIS_ENDPOINT = "audio/speech"
SYNTHESIS_MODE = "audio_speech"
ENABLED = f"services.{SPEECH_KEY}.enabled"
SHARED = f"services.{SPEECH_KEY}.shared"
ON = {ENABLED: True, SHARED: True}
OFF = {ENABLED: False, SHARED: False}
AUDIO_VARS = ("LITELLM_SPEECH_BACKEND", "LITELLM_AUDIO_ROUTES", "LITELLM_AUDIO_ALIASES")
GRANT_SCRIPT = (
    PROJECT_ROOT
    / "roles"
    / "web-app-openwebui"
    / "files"
    / "python"
    / "agent_model_grants.py"
)
CHAT = {"alias": "qwen2.5:0.5b", "name": "qwen2.5-0.5b-instruct"}
ROUTER_ALIAS = "auto"
MOCK_PROVIDER = "mock"


def _speech_services() -> dict:
    return load_yaml(str(SPEECH_DIR / ROLE_FILE_META_SERVICES))


def _speech_entity() -> dict:
    return _speech_services()[SPEECH_KEY]


def _piper_entity() -> dict:
    return _speech_services()[PIPER_KEY]


def _speech_config(path: str):
    node = {"services": _speech_services()}
    for part in path.split("."):
        node = node[part]
    return node


def _container_url(application_id: str, service_key: str) -> str:
    if (application_id, service_key) != (SPEECH_ROLE, SPEECH_KEY):
        raise AssertionError(f"unexpected container_url {application_id} {service_key}")
    port = _speech_entity()["ports"]["internal"]["http"]
    return f"http://{entity_name(application_id)}:{port}"


def _environment(flags: dict) -> NativeEnvironment:
    env = NativeEnvironment(undefined=StrictUndefined, autoescape=False)
    env.filters.update(FilterModule().filters())

    def _lookup(name, *terms, **_kwargs):
        if name == "container_url":
            return _container_url(*terms)
        if name != "config":
            raise AssertionError(f"unexpected lookup {name} {terms}")
        application_id, path = terms
        if application_id == GATEWAY_ROLE:
            return flags[path]
        if application_id == SPEECH_ROLE:
            return _speech_config(path)
        raise AssertionError(f"unexpected config lookup {application_id} {path}")

    env.globals["lookup"] = _lookup
    return env


def _piper_url() -> str:
    expression = load_yaml(str(AI_GROUP_VARS))[PIPER_URL_VAR]
    return _environment(OFF).from_string(expression).render()


def _audio_vars(flags: dict) -> dict:
    """
    Args:
        flags: the answer of ``lookup('config', 'svc-ai-litellm', <path>)`` for
            the ``speech`` flag's ``enabled`` and ``shared`` paths.

    Returns:
        ``LITELLM_SPEECH_BACKEND``, ``LITELLM_AUDIO_ROUTES`` and
        ``LITELLM_AUDIO_ALIASES`` as native values, with every
        ``svc-ai-speech`` lookup answered from that role's real
        ``meta/services.yml`` and ``PIPER_BASE_LOCAL_URL`` rendered from
        ``group_vars/all/16_ai.yml``.
    """
    env = _environment(flags)
    declared = load_yaml(str(AI_GROUP_VARS))
    values: dict = {"application_id": GATEWAY_ROLE, PIPER_URL_VAR: _piper_url()}
    for name in AUDIO_VARS:
        values[name] = env.from_string(declared[name]).render(**values)
    return values


def _routes(flags: dict) -> list[dict]:
    return _audio_vars(flags)["LITELLM_AUDIO_ROUTES"]


def _entries(config: dict) -> dict[str, dict]:
    return {entry["model_name"]: entry for entry in config.get("model_list") or []}


def _audio_entries(config: dict, mode: str) -> dict[str, dict]:
    return {
        alias: entry
        for alias, entry in _entries(config).items()
        if (entry.get("model_info") or {}).get("mode") == mode
    }


def _synthesis_routes(flags: dict) -> list[dict]:
    return [route for route in _routes(flags) if route["mode"] == SYNTHESIS_MODE]


def _inference_path(expression_name: str) -> str:
    expression = load_yaml(str(SPEECH_DIR / ROLE_FILE_VARS_MAIN))[expression_name]
    return _environment(OFF).from_string(expression).render(application_id=SPEECH_ROLE)


def _gateway_services() -> dict:
    return load_yaml(str(GATEWAY_DIR / ROLE_FILE_META_SERVICES))


def _flag_node(services: dict, path: str):
    node = {"services": services}
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _missing_flag_paths(services: dict) -> list[str]:
    return [path for path in (ENABLED, SHARED) if _flag_node(services, path) is None]


def _declared_flags(group_names: list[str]) -> dict:
    env = NativeEnvironment(undefined=StrictUndefined, autoescape=False)
    services = _gateway_services()
    return {
        path: env.from_string(str(_flag_node(services, path))).render(
            group_names=group_names
        )
        for path in (ENABLED, SHARED)
    }


class TestGatewayFlag(unittest.TestCase):
    def test_the_gateway_declares_every_flag_path_the_gate_reads(self) -> None:
        self.assertEqual(_missing_flag_paths(_gateway_services()), [])

    def test_a_services_file_without_the_speech_entry_is_caught(self) -> None:
        services = {
            key: value
            for key, value in _gateway_services().items()
            if key != SPEECH_KEY
        }
        self.assertEqual(_missing_flag_paths(services), [ENABLED, SHARED])

    def test_the_declared_flag_follows_the_speech_role(self) -> None:
        self.assertTrue(_routes(_declared_flags([SPEECH_ROLE])))
        self.assertEqual(_routes(_declared_flags([])), [])

    def test_the_synthesis_route_follows_the_speech_role(self) -> None:
        self.assertEqual(len(_synthesis_routes(_declared_flags([SPEECH_ROLE]))), 1)
        self.assertEqual(_synthesis_routes(_declared_flags([])), [])


class TestGate(unittest.TestCase):
    def test_without_the_speech_server_no_audio_route_is_published(self) -> None:
        config = render(ollama=[CHAT], audio_routes=_routes(OFF))
        self.assertEqual(_audio_entries(config, TRANSCRIPTION_MODE), {})
        self.assertEqual(set(_entries(config)), {CHAT["alias"]})

    def test_a_flag_without_the_shared_network_publishes_no_route(self) -> None:
        self.assertEqual(
            _routes({ENABLED: True, SHARED: False}),
            [],
            "the gateway reaches the speech server only on that role's network, "
            "which the shared flag attaches it to",
        )

    def test_the_speech_server_publishes_one_transcription_route(self) -> None:
        config = render(ollama=[CHAT], audio_routes=_routes(ON))
        self.assertEqual(
            set(_audio_entries(config, TRANSCRIPTION_MODE)),
            {_speech_entity()["model_alias"]},
        )

    def test_without_the_speech_server_no_synthesis_route_is_published(self) -> None:
        config = render(ollama=[CHAT], audio_routes=_routes(OFF))
        self.assertEqual(_audio_entries(config, SYNTHESIS_MODE), {})

    def test_the_speech_server_publishes_one_synthesis_route(self) -> None:
        config = render(ollama=[CHAT], audio_routes=_routes(ON))
        self.assertEqual(
            set(_audio_entries(config, SYNTHESIS_MODE)),
            {_piper_entity()["model_alias"]},
        )


class TestTranscriptionRoute(unittest.TestCase):
    def setUp(self) -> None:
        config = render(ollama=[CHAT], audio_routes=_routes(ON))
        self.entry = _entries(config)[_speech_entity()["model_alias"]]
        self.params = self.entry["litellm_params"]

    def test_the_route_reaches_the_server_inference_path(self) -> None:
        self.assertEqual(
            self.params["api_base"].rstrip("/") + "/" + TRANSCRIPTION_ENDPOINT,
            _container_url(SPEECH_ROLE, SPEECH_KEY)
            + _inference_path("SPEECH_INFERENCE_PATH"),
        )

    def test_the_route_declares_the_transcription_mode(self) -> None:
        self.assertEqual(self.entry["model_info"], {"mode": TRANSCRIPTION_MODE})

    def test_the_route_waits_as_long_as_the_server_allows_a_recording(self) -> None:
        self.assertEqual(self.params["timeout"], _speech_entity()["request_timeout"])

    def test_the_route_never_sends_a_provider_key(self) -> None:
        self.assertTrue(self.params["api_key"])
        self.assertFalse(
            str(self.params["api_key"]).startswith("os.environ/"),
            "the speech server has no authentication, so any provider key sent "
            "to it leaves the gateway for nothing",
        )

    def test_the_route_is_not_billed_as_an_openai_model(self) -> None:
        provider, model = self.params["model"].split("/", 1)
        self.assertEqual(provider, "openai")
        self.assertNotEqual(
            model,
            self.entry["model_name"],
            "LiteLLM prices whisper-1 at OpenAI's per-second rate, so a backend "
            "model named like the client alias charges a local transcription to "
            "the caller's key budget",
        )


class TestSynthesisRoute(unittest.TestCase):
    def setUp(self) -> None:
        config = render(ollama=[CHAT], audio_routes=_routes(ON))
        self.entry = _entries(config)[_piper_entity()["model_alias"]]
        self.params = self.entry["litellm_params"]

    def test_the_route_reaches_the_piper_inference_path(self) -> None:
        port = _piper_entity()["ports"]["internal"]["http"]
        self.assertEqual(
            self.params["api_base"].rstrip("/") + "/" + SYNTHESIS_ENDPOINT,
            f"http://{_piper_entity()['name']}:{port}"
            + _inference_path("PIPER_INFERENCE_PATH"),
        )

    def test_the_route_declares_the_speech_mode(self) -> None:
        self.assertEqual(self.entry["model_info"], {"mode": SYNTHESIS_MODE})

    def test_the_route_waits_as_long_as_the_server_allows_a_synthesis(self) -> None:
        self.assertEqual(self.params["timeout"], _piper_entity()["request_timeout"])

    def test_the_route_never_sends_a_provider_key(self) -> None:
        self.assertTrue(self.params["api_key"])
        self.assertFalse(str(self.params["api_key"]).startswith("os.environ/"))

    def test_the_route_is_not_billed_as_an_openai_model(self) -> None:
        provider, model = self.params["model"].split("/", 1)
        self.assertEqual(provider, "openai")
        self.assertNotEqual(model, self.entry["model_name"])


class TestModelList(unittest.TestCase):
    def test_the_chat_routes_stay_ahead_of_the_audio_route(self) -> None:
        config = render(ollama=[CHAT], audio_routes=_routes(ON))
        self.assertEqual(
            config["model_list"][0]["model_name"],
            CHAT["alias"],
            "the first route is the one LITELLM_CHAT_MODEL names",
        )

    def test_an_audio_route_alone_still_renders_a_model_list(self) -> None:
        config = render(router_alias=ROUTER_ALIAS, audio_routes=_routes(ON))
        self.assertEqual(
            set(_entries(config)),
            {_speech_entity()["model_alias"], _piper_entity()["model_alias"]},
            "the router alias exists for chat routes only, and an empty chat "
            "list must not render model_list as an empty flow sequence in front "
            "of the audio entries",
        )


def _ungranted_modes() -> tuple[str, ...]:
    for node in ast.parse(read_text(str(GRANT_SCRIPT))).body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", None) == "UNGRANTED_MODES" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{GRANT_SCRIPT} no longer assigns UNGRANTED_MODES")


def _withheld(config: dict) -> set[str]:
    modes = _ungranted_modes()
    return {
        alias
        for alias, entry in _entries(config).items()
        if (entry.get("model_info") or {}).get("mode") in modes
    }


class TestOpenWebUIGrants(unittest.TestCase):
    def test_the_spec_list_is_exactly_what_the_grant_step_withholds(self) -> None:
        config = render(ollama=[CHAT], audio_routes=_routes(ON))
        self.assertTrue(_withheld(config))
        self.assertEqual(
            set(_audio_vars(ON)["LITELLM_AUDIO_ALIASES"]),
            _withheld(config),
            "web-app-openwebui's playwright.env.j2 hands LITELLM_AUDIO_ALIASES to "
            "test-agent-broker.js as GATEWAY_UNGRANTED_MODELS_JSON, which must list "
            "every model agent_model_grants.py leaves without a grant",
        )


class TestSpeedMeasurement(unittest.TestCase):
    def test_the_audio_alias_is_left_out_of_the_speed_measurement(self) -> None:
        declared = load_yaml(str(GATEWAY_DIR / ROLE_FILE_VARS_MAIN))
        aliases = _audio_vars(ON)["LITELLM_AUDIO_ALIASES"]
        unranked = (
            _environment(ON)
            .from_string(declared["LITELLM_UNRANKED_ALIASES"])
            .render(
                LITELLM_ROUTER_ALIAS=ROUTER_ALIAS,
                AI_FREELLMAPI_MODELS=[],
                LITELLM_REMOTE_MODELS=[],
                AI_MOCK_PROVIDER=MOCK_PROVIDER,
                LITELLM_AUDIO_ALIASES=aliases,
            )
        )
        for alias in (_speech_entity()["model_alias"], _piper_entity()["model_alias"]):
            self.assertIn(alias, str(unranked).split(","))


if __name__ == "__main__":
    unittest.main()
