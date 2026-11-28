from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HEALTH_PATH = "/health"
WAV = "wav"
MEDIA_TYPES = {WAV: "audio/wav"}
JSON_TYPE = "application/json"
MAX_BODY_BYTES = 65536
STDERR_TAIL = 300
TEXT_FLAGS = (
    "--host",
    "--piper",
    "--model",
    "--config",
    "--inference-path",
    "--tmp-dir",
)
NUMBER_FLAGS = ("--port", "--speaker", "--max-input-chars", "--timeout")


@dataclass(frozen=True)
class Settings:
    """
    Args:
        piper: the piper executable.
        model: the voice's ``.onnx`` file.
        config: the voice's ``.onnx.json`` file.
        speaker: the speaker id piper reads the voice with.
        inference_path: the route that answers a speech request.
        max_input_chars: the longest input synthesized in one request.
        timeout: the seconds one synthesis may take.
        tmp_dir: where each answer is written until it is sent.
    """

    piper: str
    model: str
    config: str
    speaker: int
    inference_path: str
    max_input_chars: int
    timeout: int
    tmp_dir: str


class SynthesisError(Exception):
    """
    Args:
        status: the HTTP status the request is answered with.
        message: the reason, sent in OpenAI's error shape.
    """

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def parse_request(body: bytes, max_input_chars: int) -> tuple[str, str]:
    """
    Args:
        body: the JSON body of an OpenAI ``audio/speech`` request.
        max_input_chars: the longest input synthesized in one request.

    Returns:
        The input on one line and the response format, ``wav`` when the
        request names none.

    Raises:
        SynthesisError: the body is no JSON object, the input is empty or
            longer than *max_input_chars*, or the format is not served.
    """
    try:
        request = json.loads(body)
    except ValueError:
        raise SynthesisError(HTTPStatus.BAD_REQUEST, "the body is not JSON") from None
    if not isinstance(request, dict):
        raise SynthesisError(HTTPStatus.BAD_REQUEST, "the body is not a JSON object")
    text = request.get("input")
    if not isinstance(text, str) or not text.strip():
        raise SynthesisError(HTTPStatus.BAD_REQUEST, "input must be a non-empty string")
    if len(text) > max_input_chars:
        raise SynthesisError(
            HTTPStatus.BAD_REQUEST, f"input is longer than {max_input_chars} characters"
        )
    response_format = request.get("response_format") or WAV
    if not isinstance(response_format, str) or response_format not in MEDIA_TYPES:
        raise SynthesisError(
            HTTPStatus.BAD_REQUEST,
            f"response_format must be one of {', '.join(MEDIA_TYPES)}",
        )
    return " ".join(text.split()), response_format


def piper_command(settings: Settings, output: Path) -> list[str]:
    """
    Args:
        settings: the server's settings.
        output: the WAV file piper writes.

    Returns:
        The argv that synthesizes the line piper reads on stdin into *output*.
    """
    return [
        settings.piper,
        "--model",
        settings.model,
        "--config",
        settings.config,
        "--speaker",
        str(settings.speaker),
        "--output-file",
        str(output),
    ]


def synthesize(settings: Settings, text: str) -> bytes:
    """
    Args:
        settings: the server's settings.
        text: the input on one line.

    Returns:
        The WAV file piper wrote.

    Raises:
        SynthesisError: piper took longer than the timeout, failed or wrote
            no audio.
    """
    with tempfile.TemporaryDirectory(dir=settings.tmp_dir) as scratch:
        output = Path(scratch) / "speech.wav"
        try:
            done = subprocess.run(
                piper_command(settings, output),
                input=f"{text}\n",
                capture_output=True,
                text=True,
                timeout=settings.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise SynthesisError(
                HTTPStatus.GATEWAY_TIMEOUT,
                f"piper took longer than {settings.timeout} seconds",
            ) from None
        if done.returncode != 0 or not output.is_file() or not output.stat().st_size:
            raise SynthesisError(
                HTTPStatus.BAD_GATEWAY,
                f"piper failed with exit code {done.returncode}: "
                f"{done.stderr.strip()[-STDERR_TAIL:]}",
            )
        return output.read_bytes()


def healthy(settings: Settings) -> bool:
    """
    Args:
        settings: the server's settings.

    Returns:
        Whether piper is executable and both voice files are readable.
    """
    return os.access(settings.piper, os.X_OK) and all(
        os.access(path, os.R_OK) for path in (settings.model, settings.config)
    )


def error_body(status: HTTPStatus, message: str) -> bytes:
    """
    Args:
        status: the HTTP status of the answer.
        message: the reason.

    Returns:
        The reason in OpenAI's error shape.
    """
    kind = (
        "server_error"
        if status >= HTTPStatus.INTERNAL_SERVER_ERROR
        else "invalid_request_error"
    )
    return json.dumps(
        {"error": {"message": message, "type": kind, "code": status.value}}
    ).encode()


def handler(settings: Settings, lock: threading.Lock) -> type[BaseHTTPRequestHandler]:
    """
    Args:
        settings: the server's settings.
        lock: held while piper runs, so one synthesis runs at a time and the
            health route keeps answering.

    Returns:
        The request handler bound to *settings*.
    """

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path != HEALTH_PATH:
                self._send(
                    HTTPStatus.NOT_FOUND,
                    JSON_TYPE,
                    error_body(HTTPStatus.NOT_FOUND, "no such route"),
                )
                return
            status = (
                HTTPStatus.OK if healthy(settings) else HTTPStatus.SERVICE_UNAVAILABLE
            )
            self._send(
                status, JSON_TYPE, json.dumps({"status": status.phrase}).encode()
            )

        def do_POST(self) -> None:
            if self.path != settings.inference_path:
                self._send(
                    HTTPStatus.NOT_FOUND,
                    JSON_TYPE,
                    error_body(HTTPStatus.NOT_FOUND, "no such route"),
                )
                return
            length = self.headers.get("Content-Length") or ""
            if not length.isdigit() or not 0 < int(length) <= MAX_BODY_BYTES:
                message = f"the body must be 1 to {MAX_BODY_BYTES} bytes"
                self._send(
                    HTTPStatus.BAD_REQUEST,
                    JSON_TYPE,
                    error_body(HTTPStatus.BAD_REQUEST, message),
                )
                return
            try:
                text, response_format = parse_request(
                    self.rfile.read(int(length)), settings.max_input_chars
                )
                with lock:
                    audio = synthesize(settings, text)
            except SynthesisError as error:
                self._send(
                    error.status, JSON_TYPE, error_body(error.status, error.message)
                )
                return
            self._send(HTTPStatus.OK, MEDIA_TYPES[response_format], audio)

        def _send(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def parse_settings(argv: list[str]) -> tuple[str, int, Settings]:
    """
    Args:
        argv: the command line without the program name.

    Returns:
        The address to bind, the port and the server's settings.
    """
    parser = argparse.ArgumentParser()
    for flag in TEXT_FLAGS:
        parser.add_argument(flag, required=True)
    for flag in NUMBER_FLAGS:
        parser.add_argument(flag, required=True, type=int)
    args = parser.parse_args(argv)
    settings = Settings(
        piper=args.piper,
        model=args.model,
        config=args.config,
        speaker=args.speaker,
        inference_path=args.inference_path,
        max_input_chars=args.max_input_chars,
        timeout=args.timeout,
        tmp_dir=args.tmp_dir,
    )
    return args.host, args.port, settings


def main() -> None:
    host, port, settings = parse_settings(sys.argv[1:])
    ThreadingHTTPServer(
        (host, port), handler(settings, threading.Lock())
    ).serve_forever()


if __name__ == "__main__":
    main()
