#!/usr/bin/env python3
"""Manage Codex's shared CLI/editor connection without replacing saved logins.

Inputs:
    Deployment stdin: gateway_url, gateway_key, model, initial_mode,
        subscription_model, context_tokens, auto_compact_tokens,
        editor_data_dir, helper_path and credential_timeout_ms.
    CLI mode: gateway/api, abo, status, or credential (Codex's private auth pipe).
Outputs:
    Mode/status messages; credential writes only the token to its caller.
"""

import argparse
import datetime as dt
import json
import os
import sys
import tempfile
import tomllib
from pathlib import Path
from urllib.parse import urlsplit


def write_private(path, content):
    if path.exists() and path.read_text() == content:
        changed = path.stat().st_mode & 0o777 != 0o600
        path.chmod(0o600)
        return changed
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(content)
        Path(temporary).replace(path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return True


def toml_value(value):
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return (
            "{ "
            + ", ".join(
                f"{toml_value(key)} = {toml_value(item)}" for key, item in value.items()
            )
            + " }"
        )
    raise TypeError("Unsupported Codex TOML value; configuration was not written")


def read_state(home):
    path = home / ".config/infinito/codex.json"
    return json.loads(path.read_text()) if path.exists() else None


def configure(home, payload, mode=None):
    editor = payload["editor_data_dir"]
    if editor:
        if not Path(editor).is_absolute():
            raise ValueError("editor_data_dir must be absolute or empty")
        lock = Path(editor) / "SingletonLock"
        if lock.exists() or lock.is_symlink():
            raise ValueError("Close Code before changing the Codex connection")
    stored = read_state(home)
    if mode is None:
        mode = stored["mode"] if stored is not None else payload["initial_mode"]
    if mode not in ("gateway", "abo"):
        raise ValueError("Codex mode must be gateway or abo")
    if payload["reasoning_effort"] not in ("minimal", "low", "medium", "high", "xhigh"):
        raise ValueError("Configure a supported nonzero Codex reasoning effort")
    if not payload["model"] or not payload["gateway_key"]:
        raise ValueError("Configure the Codex model and gateway credential")
    url = urlsplit(payload["gateway_url"])
    if (
        url.scheme not in ("http", "https")
        or not url.hostname
        or url.username
        or url.password
    ):
        raise ValueError(
            "gateway_url must be an absolute HTTP(S) URL without credentials"
        )
    if not Path(payload["helper_path"]).is_absolute():
        raise ValueError("helper_path must be absolute")
    if (
        type(payload["credential_timeout_ms"]) is not int
        or payload["credential_timeout_ms"] <= 0
    ):
        raise ValueError("credential_timeout_ms must be positive")
    context = payload["context_tokens"]
    compact = payload["auto_compact_tokens"]
    if type(context) is not int or context < 0:
        raise ValueError("context_tokens must be positive or 0")
    if type(compact) is not int or (compact and not 0 < compact < context):
        raise ValueError(
            "auto_compact_tokens must be positive and below context_tokens, or 0"
        )
    path = home / ".codex/config.toml"
    config = tomllib.loads(path.read_text()) if path.exists() else {}
    for key in (
        "model",
        "model_provider",
        "model_reasoning_effort",
        "forced_login_method",
        "model_context_window",
        "model_auto_compact_token_limit",
    ):
        config.pop(key, None)
    providers = config.setdefault("model_providers", {})
    providers.pop("infinito", None)
    if mode == "gateway":
        config["model"] = payload["model"]
        config["model_provider"] = "infinito"
        config["model_reasoning_effort"] = payload["reasoning_effort"]
        if context:
            config["model_context_window"] = context
        if compact:
            config["model_auto_compact_token_limit"] = compact
        providers["infinito"] = {
            "name": "Infinito.Nexus gateway",
            "base_url": payload["gateway_url"].rstrip("/"),
            "wire_api": "responses",
            "auth": {
                "command": payload["helper_path"],
                "args": ["credential"],
                "timeout_ms": payload["credential_timeout_ms"],
                "refresh_interval_ms": 0,
            },
        }
    else:
        config["model_provider"] = "openai"
        config["forced_login_method"] = "chatgpt"
        if payload["subscription_model"]:
            config["model"] = payload["subscription_model"]
    content = "".join(
        f"{toml_value(key)} = {toml_value(value)}\n" for key, value in config.items()
    )
    if tomllib.loads(content) != config:
        raise ValueError("Codex TOML round-trip failed; configuration was not written")
    state = (
        json.dumps({"mode": mode, "payload": payload}, ensure_ascii=False, indent=2)
        + "\n"
    )
    changed = write_private(path, content)
    changed = write_private(home / ".config/infinito/codex.json", state) or changed
    legacy = home / ".config/environment.d/50-infinito-codex.conf"
    if legacy.exists():
        legacy.unlink()
        changed = True
    return changed


def execute(home, args):
    if args.deploy:
        print("CHANGED" if configure(home, json.load(sys.stdin)) else "UNCHANGED")
        return
    stored = read_state(home)
    if stored is None:
        raise ValueError("Deploy dsk-gnt-codex before using codex-mode")
    if args.mode == "status":
        print(stored["mode"])
    elif args.mode == "credential":
        if stored["mode"] != "gateway" or not stored["payload"]["gateway_key"]:
            raise ValueError("Gateway authentication is disabled in subscription mode")
        print(stored["payload"]["gateway_key"])
    else:
        mode = "gateway" if args.mode == "api" else args.mode
        configure(home, stored["payload"], mode)
        print(f"Codex mode: {mode}. Reopen Code and start a new Codex session.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", nargs="?", choices=("gateway", "api", "abo", "status", "credential")
    )
    parser.add_argument("--deploy", action="store_true")
    args = parser.parse_args()
    if bool(args.mode) == args.deploy:
        parser.error("Specify a connection mode or --deploy")
    home = Path.home()
    if (
        os.environ.get("CODEX_HOME")
        and Path(os.environ["CODEX_HOME"]).resolve() != (home / ".codex").resolve()
    ):
        parser.exit(1, "Unset CODEX_HOME: this deployment manages ~/.codex.\n")
    try:
        execute(home, args)
    except (ValueError, KeyError, TypeError, OSError):
        parser.exit(
            1,
            "Codex configuration failed; check the managed configuration and close Code before switching.\n",
        )


if __name__ == "__main__":
    main()
