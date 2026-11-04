import argparse
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path


def validate(program, home, timeout):
    spec = importlib.util.spec_from_file_location(
        "codex_mode",
        program,
        loader=importlib.machinery.SourceFileLoader("codex_mode", str(program)),
    )
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    stored = manager.read_state(home)
    if stored is None:
        raise ValueError("Deploy the Codex gateway connection before validation")
    payload = stored["payload"]
    binaries = [shutil.which("codex")]
    binaries.extend(
        str(path)
        for path in home.glob(".vscode*/extensions/openai.chatgpt-*/bin/linux-*/codex")
    )
    if binaries[0] is None:
        raise ValueError("Codex CLI is missing")
    with tempfile.TemporaryDirectory(
        prefix="codex-validation-", dir="/tmp"
    ) as directory:
        fixture = Path(directory)
        helper = fixture / "codex-mode"
        shutil.copyfile(program, helper)
        helper.chmod(0o700)
        test_payload = dict(payload, editor_data_dir="", helper_path=str(helper))
        environment = {
            key: value
            for key, value in os.environ.items()
            if key
            not in (
                "OPENAI_API_KEY",
                "OPENAI_BASE_URL",
                "INFINITO_GATEWAY_KEY",  # nocheck: legacy Codex credential variable stripped from the probe environment
                "CODEX_HOME",
            )
        }
        environment.update(HOME=directory, CODEX_HOME=str(fixture / ".codex"))
        for mode in ("gateway", "abo"):
            manager.configure(fixture, test_payload, mode)
            for binary in binaries:
                result = subprocess.run(
                    [binary, "--strict-config", "app-server", "--print-startup-config"],
                    cwd=fixture,
                    env=environment,
                    capture_output=True,
                    check=False,
                    timeout=timeout,
                )
                if result.returncode:
                    raise ValueError(
                        "Installed Codex rejected the managed connection configuration"
                    )
        manager.configure(fixture, test_payload, "gateway")
        credential = subprocess.run(
            [str(helper), "credential"],
            env=environment,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
        if (
            credential.returncode
            or credential.stdout.decode().strip() != payload["gateway_key"]
        ):
            raise ValueError("Codex credential helper failed")
    request = urllib.request.Request(  # noqa: S310 — configure() validates the HTTP(S) URL before this request.
        payload["gateway_url"].rstrip("/") + "/responses",
        headers={
            "Authorization": "Bearer " + payload["gateway_key"],
            "Content-Type": "application/json",
        },
        data=json.dumps(
            {
                "model": payload["model"],
                "input": "Reply only OK.",
                "max_output_tokens": payload["validation_output_tokens"],
                "reasoning": {"effort": payload["reasoning_effort"]},
                "store": False,
            }
        ).encode(),
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — configure() validates the HTTP(S) URL before this request.
        data = json.load(response)
    if (
        data.get("object") != "response"
        or data.get("error")
        or not any(
            block.get("type") == "output_text"
            and isinstance(block.get("text"), str)
            and block["text"].strip()
            for item in (data.get("output") or [])
            if isinstance(item, dict) and item.get("type") == "message"
            for block in (item.get("content") or [])
            if isinstance(block, dict)
        )
    ):
        raise ValueError("Gateway did not return a Responses API response")
    print("Codex CLI/editor configurations, credential helper and Responses API: OK")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--program", required=True)
    parser.add_argument("--home", required=True)
    parser.add_argument("--timeout", type=int, required=True)
    args = parser.parse_args()
    try:
        validate(Path(args.program), Path(args.home), args.timeout)
    except urllib.error.HTTPError as error:
        parser.exit(1, f"Codex Responses API validation failed: HTTP {error.code}\n")
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        parser.exit(
            1,
            "Codex validation failed; check the installed client, managed connection and gateway.\n",
        )


if __name__ == "__main__":
    main()
