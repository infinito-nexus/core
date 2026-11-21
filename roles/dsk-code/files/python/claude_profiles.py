#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path

MANAGED_ENVIRONMENT = {
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_FABLE_MODEL",
    "ANTHROPIC_PROFILE",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "CLAUDE_CODE_SUBAGENT_MODEL",
    "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
}


def read_settings(path):
    text = path.read_text() if path.exists() else "{}"
    text = re.sub(
        r'("(?:\\.|[^"\\])*")|//[^\n]*|/\*.*?\*/',
        lambda match: match[1] if match[1] is not None else " ",
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'("(?:\\.|[^"\\])*")|,(\s*[}\]])',
        lambda match: match[1] if match[1] is not None else match[2],
        text,
    )
    result = json.loads(text)
    if not isinstance(result, dict):
        raise TypeError(f"Expected a settings object in {path}")
    return result


def merge(settings, enforced):
    merged = dict(settings)
    for key, value in enforced.items():
        current = merged.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            merged[key] = merge(current, value)
        else:
            merged[key] = value
    return merged


def write_json(path, value):
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
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


def profile_settings(profile, gateway_url, gateway_key):
    mode = profile["mode"]
    if mode == "subscription":
        return {
            "claudeCode.disableLoginPrompt": False,
            "claudeCode.environmentVariables": [],
        }
    if mode != "gateway":
        raise ValueError("Profile mode must be gateway or subscription")
    model = profile["model"]
    if not model or not gateway_url or not gateway_key:
        raise ValueError("Gateway profiles require model, gateway_url and gateway_key")
    environment = {
        "ANTHROPIC_BASE_URL": gateway_url,
        "ANTHROPIC_AUTH_TOKEN": gateway_key,
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_MODEL": model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
        "CLAUDE_CODE_SUBAGENT_MODEL": model,
        "CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY": "1",
    }
    context = profile["context_tokens"]
    if context is not None:
        if type(context) is not int or context <= 0:
            raise ValueError("context_tokens must be a positive integer or null")
        environment["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(context)
    return {
        "claudeCode.disableLoginPrompt": True,
        "claudeCode.environmentVariables": [
            {"name": name, "value": value} for name, value in environment.items()
        ],
    }


def configure(user_data_dir, payload):
    if not user_data_dir.is_absolute():
        raise ValueError("user_data_dir must be an absolute editor data directory")
    lock = user_data_dir / "SingletonLock"
    if lock.exists() or lock.is_symlink():
        raise ValueError(
            "Close Code before deploying its profiles; SingletonLock exists"
        )
    if payload.get("unified"):
        return configure_unified(Path.home(), user_data_dir, payload)
    storage_path = user_data_dir / "User/globalStorage/storage.json"
    storage = read_settings(storage_path)
    stored_profiles = storage.setdefault("userDataProfiles", [])
    profiles_home = user_data_dir / "User/profiles"
    writes = []
    names = set()
    for profile in payload["profiles"]:
        name = profile["name"]
        if not name or name in names:
            raise ValueError("Each requested profile must have a unique non-empty name")
        names.add(name)
        matches = [entry for entry in stored_profiles if entry["name"] == name]
        if len(matches) > 1:
            raise ValueError("Multiple editor profiles have the same requested name")
        if matches:
            entry = matches[0]
        else:
            entry = {"name": name, "location": uuid.uuid4().hex}
            stored_profiles.append(entry)
        if entry.get("useDefaultFlags", {}).get("settings"):
            raise ValueError(
                "Disable settings inheritance on the requested editor profile"
            )
        location = entry["location"]
        if not isinstance(location, str) or Path(location).name != location:
            raise ValueError("Expected a relative profile directory identifier")
        path = profiles_home / location / "settings.json"
        if not path.resolve().is_relative_to(profiles_home.resolve()):
            raise ValueError(
                "Profile settings must stay inside the editor profiles directory"
            )
        settings = merge(read_settings(path), payload["code_settings"])
        managed = profile_settings(
            profile, payload["gateway_url"], payload["gateway_key"]
        )
        unrelated_environment = [
            item
            for item in settings.get("claudeCode.environmentVariables", [])
            if item["name"] not in MANAGED_ENVIRONMENT
        ]
        managed["claudeCode.environmentVariables"] = (
            unrelated_environment + managed["claudeCode.environmentVariables"]
        )
        settings.update(managed)
        writes.append((path, settings))
    changed = False
    for path, settings in writes:
        changed = write_json(path, settings) or changed
    return write_json(storage_path, storage) or changed


def configure_unified(home, user_data_dir, payload, mode=None):
    lock = user_data_dir / "SingletonLock"
    if lock.exists() or lock.is_symlink():
        raise ValueError("Close Code before changing the Claude connection mode")
    unified = payload["unified"]
    config_path = home / ".config/infinito/claude.json"
    stored = read_settings(config_path)
    if mode is None:
        mode = stored["mode"] if stored else unified["initial_mode"]
    if mode not in ("gateway", "abo"):
        raise ValueError("Claude mode must be gateway or abo")
    if not user_data_dir.is_absolute():
        raise ValueError("user_data_dir must be an absolute editor data directory")
    if not unified["background_model"]:
        raise ValueError("Unified background_model must be configured explicitly")
    profile = {
        "name": unified["name"],
        "mode": "gateway" if mode == "gateway" else "subscription",
        "model": unified["model"],
        "context_tokens": unified["context_tokens"],
    }
    managed = profile_settings(profile, payload["gateway_url"], payload["gateway_key"])
    environment = {
        item["name"]: item["value"]
        for item in managed["claudeCode.environmentVariables"]
    }
    if mode == "gateway":
        output_tokens = unified["max_output_tokens"]
        if (
            type(output_tokens) is not int
            or not 0 < output_tokens < unified["context_tokens"]
        ):
            raise ValueError(
                "max_output_tokens must be positive and below context_tokens"
            )
        environment["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(output_tokens)
        environment["ANTHROPIC_DEFAULT_MODEL"] = unified["model"]
        for key in (
            "CLAUDE_CODE_USE_BEDROCK",
            "CLAUDE_CODE_USE_VERTEX",
            "CLAUDE_CODE_USE_FOUNDRY",
        ):
            environment[key] = "0"
        environment["ANTHROPIC_PROFILE"] = ""
        environment["CLAUDE_CODE_OAUTH_TOKEN"] = ""
        for key in (
            "ANTHROPIC_DEFAULT_HAIKU_MODEL",
            "ANTHROPIC_DEFAULT_SONNET_MODEL",
            "ANTHROPIC_DEFAULT_OPUS_MODEL",
            "ANTHROPIC_DEFAULT_FABLE_MODEL",
            "CLAUDE_CODE_SUBAGENT_MODEL",
        ):
            environment[key] = unified["background_model"]
    else:
        environment = dict.fromkeys(sorted(MANAGED_ENVIRONMENT), "")
        environment["ANTHROPIC_DEFAULT_FABLE_MODEL"] = ""
    managed["claudeCode.environmentVariables"] = [
        {"name": key, "value": value} for key, value in sorted(environment.items())
    ]
    settings = dict(unified["settings"])
    if set(settings) & {"env", "model", "apiKeyHelper", "modelPicker"}:
        raise ValueError(
            "Unified settings must not override env, model, apiKeyHelper or modelPicker"
        )
    settings["env"] = environment
    settings["apiKeyHelper"] = ""
    if mode == "gateway":
        options = unified["gateway_models"]
        ids = [item["model"] for item in options]
        if not ids or len(ids) != len(set(ids)) or unified["model"] not in ids:
            raise ValueError("gateway_models must contain unique IDs including model")
        for item in options:
            if (
                not all(
                    isinstance(item[key], str) and item[key]
                    for key in ("model", "label", "description")
                )
                or "[1m]" in item["model"].lower()
            ):
                raise ValueError(
                    "gateway_models require model, label, description and no [1m] suffix"
                )
        settings["modelPicker"] = {"options": options, "replaceBuiltInOptions": True}
        settings["model"] = unified["model"]
    else:
        if not unified["subscription_model"]:
            raise ValueError("Unified subscription_model must be configured explicitly")
        settings["model"] = unified["subscription_model"]

    storage_path = user_data_dir / "User/globalStorage/storage.json"
    storage = read_settings(storage_path)
    entries = storage.get("userDataProfiles", [])
    retired = set(unified["retire_profiles"])
    name = unified["name"]
    if name in retired or not name:
        raise ValueError("Unified profile name must be nonempty and not retired")
    matches = [entry for entry in entries if entry["name"] == name]
    if len(matches) > 1:
        raise ValueError("Multiple editor profiles have the unified name")
    entry = matches[0] if matches else {"name": name, "location": uuid.uuid4().hex}
    location = entry["location"]
    profiles_home = user_data_dir / "User/profiles"
    path = profiles_home / location / "settings.json"
    if (
        not isinstance(location, str)
        or Path(location).name != location
        or not path.resolve().is_relative_to(profiles_home.resolve())
    ):
        raise ValueError("Unified profile must stay inside the profiles directory")
    if entry.get("useDefaultFlags", {}).get("settings"):
        raise ValueError("Disable settings inheritance on the unified profile")
    storage["userDataProfiles"] = [
        item for item in entries if item["name"] not in retired and item["name"] != name
    ] + [entry]
    retired_locations = {
        item["location"] for item in entries if item["name"] in retired
    }
    associations = storage.get("profileAssociations", {})
    for kind in ("workspaces", "emptyWindows"):
        for resource, profile_id in associations.get(kind, {}).items():
            if profile_id in retired_locations:
                associations[kind][resource] = location
    config = {"mode": mode, "user_data_dir": str(user_data_dir), "payload": payload}
    writes = [
        (home / ".claude/settings.json", settings),
        (user_data_dir / "User/settings.json", payload["code_settings"]),
        (path, dict(payload["code_settings"], **managed)),
        (storage_path, storage),
        (config_path, config),
    ]
    changed = False
    for target, value in writes:
        changed = write_json(target, value) or changed
    return changed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user-data-dir")
    parser.add_argument("mode", nargs="?", choices=("gateway", "abo", "status"))
    arguments = parser.parse_args()
    try:
        if arguments.mode:
            home = Path.home()
            config = read_settings(home / ".config/infinito/claude.json")
            if not config:
                parser.exit(1, "Deploy the unified Claude configuration first.\n")
            if arguments.mode == "status":
                print(config["mode"])
                return
            configure_unified(
                home, Path(config["user_data_dir"]), config["payload"], arguments.mode
            )
            print(
                f"Claude mode: {arguments.mode}. Reopen Code and start a new Claude session."
            )
        else:
            if not arguments.user_data_dir:
                parser.error("--user-data-dir is required for deployment")
            changed = configure(Path(arguments.user_data_dir), json.load(sys.stdin))
            print("CHANGED" if changed else "UNCHANGED")
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(
            1,
            f"Claude configuration failed: {error}\n",
        )


if __name__ == "__main__":
    main()
