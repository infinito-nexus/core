"""Talk transcribes recordings exactly while a speech-to-text backend is deployed.

An enabled ``integration_openai`` is no speech-to-text provider: its backend is
Open WebUI's ``/api`` or LiteLLM's ``/v1``, and neither serves
``/audio/transcriptions``. Gating spreed's ``call_recording_summary`` on the
addon alone made every stored recording schedule a ``core:audio2text`` task that
failed with 413 and notified the owner "Failed to transcript call recording".
spreed's transcript and summary, integration_openai's ``stt_provider_enabled``
and its STT route now follow the ``speech`` service flag, which is on exactly
while ``svc-ai-speech`` is part of the deployment, so no inventory has to
declare a backend by hand.
"""

from __future__ import annotations

import itertools
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_DIR_META_ADDONS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

APPLICATION_ID = "web-app-nextcloud"
SPEECH_ROLE = "svc-ai-speech"
SPEECH_KEY = "speech"
ROLE_DIR = Path(PROJECT_ROOT) / "roles" / APPLICATION_ID
SPEECH_DIR = Path(PROJECT_ROOT) / "roles" / SPEECH_ROLE
ADDONS_DIR = ROLE_DIR / ROLE_DIR_META_ADDONS
GATE = "NEXTCLOUD_SPEECH_TO_TEXT_ENABLED"
ROLE_VARS = (GATE, "NEXTCLOUD_SPEECH_TO_TEXT_URL", "NEXTCLOUD_SPEECH_TO_TEXT_TIMEOUT")
ADDON = "addons.integration_openai.enabled"
FLAG = f"services.{SPEECH_KEY}.enabled"
SHARED = f"services.{SPEECH_KEY}.shared"
TRANSCRIPTION_ENDPOINT = "audio/transcriptions"
UPSTREAM_DEFAULT_TIMEOUT = 240
RECORDED_HOUR = 3600
OFF = {ADDON: True, FLAG: False, SHARED: False}
ON = {ADDON: True, FLAG: True, SHARED: True}
NOTHING = {"transcript": "no", "summary": "no", "provider": "0", "url": ""}


def _ansible_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"y", "yes", "true", "on", "1"}
    return bool(value)


def _speech_entity() -> dict:
    return load_yaml(str(SPEECH_DIR / ROLE_FILE_META_SERVICES))[SPEECH_KEY]


def _speech_config(path: str):
    node = {"services": {SPEECH_KEY: _speech_entity()}}
    for part in path.split("."):
        node = node[part]
    return node


def _container_url(application_id: str, service_key: str) -> str:
    port = _speech_entity()["ports"]["internal"]["http"]
    if application_id != SPEECH_ROLE or service_key != SPEECH_KEY:
        raise AssertionError(f"unexpected container_url {application_id} {service_key}")
    return f"http://{entity_name(application_id)}:{port}"


def _configvalue(addon: str, configkey: str) -> str:
    spec = load_yaml(str(ADDONS_DIR / f"{addon}.yml"))
    for item in spec["config"]["plugin_configuration"]:
        if item["configkey"] == configkey:
            return item["configvalue"]
    raise KeyError(f"{addon} sets no {configkey}")


def _environment(config: dict) -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = _ansible_bool

    def _lookup(name, *terms, **_kwargs):
        if name == "container_url":
            return _container_url(*terms)
        if name != "config":
            raise AssertionError(f"unexpected lookup {name} {terms}")
        application_id, path = terms[0], terms[1]
        if application_id == APPLICATION_ID:
            return config[path]
        if application_id == SPEECH_ROLE:
            return _speech_config(path)
        raise AssertionError(f"unexpected config lookup {application_id} {path}")

    env.globals["lookup"] = _lookup
    return env


def _render(expression: str, config: dict) -> str:
    """Render one role expression against stubbed lookups.

    Args:
        expression: the Jinja expression of a var or a ``configvalue``.
        config: the answer of ``lookup('config', 'web-app-nextcloud', <path>)``
            per path; ``svc-ai-speech`` paths and ``container_url`` answer from
            that role's real ``meta/services.yml``.

    Returns:
        The rendered string, with the speech-to-text vars of vars/main.yml
        rendered against the same lookups first.
    """
    env = _environment(config)
    declared = load_yaml(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))
    variables = {"application_id": APPLICATION_ID}
    for name in ROLE_VARS:
        variables[name] = env.from_string(declared[name]).render(**variables).strip()
    return env.from_string(expression).render(**variables).strip()


def _wiring(config: dict) -> dict[str, str]:
    return {
        "transcript": _render(
            _configvalue("spreed", "call_recording_transcription"), config
        ),
        "summary": _render(_configvalue("spreed", "call_recording_summary"), config),
        "provider": _render(
            _configvalue("integration_openai", "stt_provider_enabled"), config
        ),
        "url": _render(_configvalue("integration_openai", "stt_url"), config),
    }


class TestSpeechToTextGate(unittest.TestCase):
    def test_no_manual_declaration_is_left(self) -> None:
        config = load_yaml(str(ADDONS_DIR / "integration_openai.yml"))["config"]
        gate = load_yaml(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))[GATE]

        self.assertNotIn("speech_to_text", config)
        self.assertNotIn("addons.integration_openai.config", gate)

    def test_the_speech_flag_follows_the_deployed_backend(self) -> None:
        flag = load_yaml(str(ROLE_DIR / ROLE_FILE_META_SERVICES))[SPEECH_KEY]
        env = _environment({})

        self.assertEqual(entity_name(SPEECH_ROLE), SPEECH_KEY)
        for key in ("enabled", "shared"):
            for group_names, expected in (([], False), ([SPEECH_ROLE], True)):
                with self.subTest(key=key, group_names=group_names):
                    rendered = env.from_string(flag[key]).render(
                        group_names=group_names
                    )
                    self.assertIs(_ansible_bool(rendered), expected)

    def test_the_gate_needs_the_addon_and_a_reachable_backend(self) -> None:
        expression = "{{ " + GATE + " }}"
        for addon, enabled, shared in itertools.product((False, True), repeat=3):
            with self.subTest(addon=addon, enabled=enabled, shared=shared):
                rendered = _render(
                    expression, {ADDON: addon, FLAG: enabled, SHARED: shared}
                )
                self.assertIs(_ansible_bool(rendered), addon and enabled and shared)

    def test_an_openai_backend_without_speech_backend_transcribes_nothing(
        self,
    ) -> None:
        self.assertEqual(_wiring(OFF), NOTHING)

    def test_a_deployed_backend_turns_transcript_summary_and_route_on(self) -> None:
        self.assertEqual(
            _wiring(ON),
            {
                "transcript": "yes",
                "summary": "yes",
                "provider": "1",
                "url": _container_url(SPEECH_ROLE, SPEECH_KEY) + "/v1",
            },
        )

    def test_the_backend_without_the_addon_turns_nothing_on(self) -> None:
        self.assertEqual(_wiring({ADDON: False, FLAG: True, SHARED: True}), NOTHING)

    def test_the_route_reaches_the_server_inference_path(self) -> None:
        url = _wiring(ON)["url"]
        inference_path = (
            _environment({})
            .from_string(
                load_yaml(str(SPEECH_DIR / ROLE_FILE_VARS_MAIN))[
                    "SPEECH_INFERENCE_PATH"
                ]
            )
            .render(application_id=SPEECH_ROLE)
        )

        self.assertEqual(
            url.rstrip("/") + "/" + TRANSCRIPTION_ENDPOINT,
            _container_url(SPEECH_ROLE, SPEECH_KEY) + inference_path,
        )

    def test_the_request_waits_as_long_as_the_server_allows_a_recording(
        self,
    ) -> None:
        timeout = _render(_configvalue("integration_openai", "stt_request_timeout"), ON)

        self.assertEqual(int(timeout), _speech_entity()["request_timeout"])
        self.assertGreaterEqual(int(timeout), RECORDED_HOUR)
        self.assertGreater(int(timeout), UPSTREAM_DEFAULT_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
