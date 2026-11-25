from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
from unittest.mock import patch

from utils import PROJECT_ROOT

SCRIPT_PATH = Path(PROJECT_ROOT) / "roles/svc-ai-speech/files/python/server.py"
MAX_CHARS = 16
WAV_BYTES = b"RIFF\x24\x00\x00\x00WAVEfmt "


def _load():
    spec = importlib.util.spec_from_file_location("piper_openai_server", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SERVER = _load()


def _body(**fields) -> bytes:
    return json.dumps(fields).encode()


def _settings(scratch: str):
    return SERVER.Settings(
        piper=str(Path(scratch) / "piper"),
        model=str(Path(scratch) / "voice.onnx"),
        config=str(Path(scratch) / "voice.onnx.json"),
        speaker=0,
        inference_path="/v1/audio/speech",
        max_input_chars=MAX_CHARS,
        timeout=5,
        tmp_dir=scratch,
    )


def _piper_writes(payload: bytes, returncode: int):
    def _run(argv, **_kwargs):
        Path(argv[argv.index("--output-file") + 1]).write_bytes(payload)
        return subprocess.CompletedProcess(argv, returncode, stdout="", stderr="boom")

    return _run


class TestParseRequest(unittest.TestCase):
    def test_an_openai_request_yields_one_line_and_wav(self) -> None:
        text, response_format = SERVER.parse_request(
            _body(model="tts-1", input="Hello\n world", voice="alloy"), MAX_CHARS
        )

        self.assertEqual(text, "Hello world")
        self.assertEqual(response_format, "wav")

    def test_wav_is_served_when_named(self) -> None:
        self.assertEqual(
            SERVER.parse_request(_body(input="Hi", response_format="wav"), MAX_CHARS)[
                1
            ],
            "wav",
        )

    def test_a_format_piper_does_not_write_is_refused(self) -> None:
        for response_format in ("mp3", "opus", ["wav"]):
            with self.assertRaises(SERVER.SynthesisError) as caught:
                SERVER.parse_request(
                    _body(input="Hi", response_format=response_format), MAX_CHARS
                )
            self.assertEqual(caught.exception.status, HTTPStatus.BAD_REQUEST)

    def test_an_empty_or_missing_input_is_refused(self) -> None:
        for body in (_body(input=""), _body(input="  \n"), _body(model="tts-1")):
            with self.assertRaises(SERVER.SynthesisError):
                SERVER.parse_request(body, MAX_CHARS)

    def test_an_input_over_the_limit_is_refused(self) -> None:
        with self.assertRaises(SERVER.SynthesisError):
            SERVER.parse_request(_body(input="x" * (MAX_CHARS + 1)), MAX_CHARS)

    def test_a_body_that_is_no_json_object_is_refused(self) -> None:
        for body in (b"", b"not json", b"[1]", b"\xff"):
            with self.assertRaises(SERVER.SynthesisError):
                SERVER.parse_request(body, MAX_CHARS)


class TestSynthesize(unittest.TestCase):
    def test_piper_reads_the_voice_and_speaker_from_the_settings(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            settings = _settings(scratch)
            command = SERVER.piper_command(settings, Path(scratch) / "out.wav")

        self.assertEqual(command[0], settings.piper)
        self.assertEqual(command[command.index("--model") + 1], settings.model)
        self.assertEqual(command[command.index("--config") + 1], settings.config)
        self.assertEqual(command[command.index("--speaker") + 1], "0")

    def test_the_wav_piper_writes_is_the_answer(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            with patch.object(SERVER.subprocess, "run", _piper_writes(WAV_BYTES, 0)):
                audio = SERVER.synthesize(_settings(scratch), "Hello")
            leftovers = list(Path(scratch).iterdir())

        self.assertEqual(audio, WAV_BYTES)
        self.assertEqual(leftovers, [], "each answer is deleted once it is read")

    def test_a_failed_or_silent_piper_is_a_gateway_error(self) -> None:
        for payload, returncode in ((WAV_BYTES, 1), (b"", 0)):
            with (
                tempfile.TemporaryDirectory() as scratch,
                patch.object(
                    SERVER.subprocess, "run", _piper_writes(payload, returncode)
                ),
                self.assertRaises(SERVER.SynthesisError) as caught,
            ):
                SERVER.synthesize(_settings(scratch), "Hello")
            self.assertEqual(caught.exception.status, HTTPStatus.BAD_GATEWAY)

    def test_a_slow_piper_times_out(self) -> None:
        timeout = subprocess.TimeoutExpired(cmd="piper", timeout=5)
        with (
            tempfile.TemporaryDirectory() as scratch,
            patch.object(SERVER.subprocess, "run", side_effect=timeout),
            self.assertRaises(SERVER.SynthesisError) as caught,
        ):
            SERVER.synthesize(_settings(scratch), "Hello")

        self.assertEqual(caught.exception.status, HTTPStatus.GATEWAY_TIMEOUT)


class TestHealth(unittest.TestCase):
    def test_the_server_is_healthy_only_with_piper_and_both_voice_files(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            settings = _settings(scratch)
            self.assertFalse(SERVER.healthy(settings))
            Path(settings.piper).write_bytes(b"")
            Path(settings.piper).chmod(0o755)
            Path(settings.model).write_bytes(b"")
            self.assertFalse(SERVER.healthy(settings))
            Path(settings.config).write_bytes(b"")
            self.assertTrue(SERVER.healthy(settings))

    def test_errors_carry_the_openai_shape(self) -> None:
        error = json.loads(SERVER.error_body(HTTPStatus.BAD_REQUEST, "nope"))["error"]

        self.assertEqual(error["message"], "nope")
        self.assertEqual(error["type"], "invalid_request_error")
        self.assertEqual(error["code"], HTTPStatus.BAD_REQUEST.value)


if __name__ == "__main__":
    unittest.main()
