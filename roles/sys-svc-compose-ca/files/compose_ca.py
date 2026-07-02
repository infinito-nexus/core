#!/usr/bin/env python3
# nocheck: file-size — single-host CA orchestration script. Ships as one
# file because it is delivered to the target via `ansible.builtin.copy`
# and must run with only the Python stdlib available; splitting it would
# require also delivering a package, which the role does not do.
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

# This script is deployed to the target host via `ansible.builtin.copy`
# (see roles/sys-svc-compose-ca/tasks/01_core.yml). The deploy target
# does NOT have the project's `utils/` package on PYTHONPATH, so direct
# yaml.safe_load / yaml.safe_dump are the only option here. Each call
# below carries an explicit `# nocheck: direct-yaml` marker that the lint
# `tests/lint/repository/yaml/test_no_direct_calls.py` honours.
import yaml


def die(msg: str, code: int = 2) -> None:
    print(f"[compose_ca] {msg}", file=sys.stderr)
    raise SystemExit(code)


def run(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int = 600,
    capture: bool = True,
) -> tuple[int, str, str]:
    # killpg the whole group on timeout: a daemon-side docker/buildx grandchild
    # can keep the captured pipe open and make subprocess's own timeout inert.
    pipe = subprocess.PIPE if capture else subprocess.DEVNULL
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=pipe,
        stderr=pipe,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
        try:
            out, err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        return 124, (out or ""), f"timed out after {timeout}s: {' '.join(cmd)}"
    return proc.returncode, (out or ""), (err or "")


def run_checked(cmd: list[str], *, cwd: Path, env: dict[str, str], label: str) -> None:
    rc, out, err = run(cmd, cwd=cwd, env=env)
    if rc != 0:
        die(f"{label} failed (rc={rc})\nSTDERR:\n{err.strip()}\nSTDOUT:\n{out.strip()}")


def parse_yaml(text: str, label: str) -> dict[str, Any]:
    try:
        doc = yaml.safe_load(text)  # nocheck: direct-yaml
    except Exception as e:
        die(f"Failed to parse YAML for {label}: {e}")
    if not isinstance(doc, dict):
        die(f"{label} must be a mapping at top-level")
    return doc


def _is_shell_form(argv: list[str]) -> bool:
    return (
        len(argv) >= 2
        and argv[0] in {"/bin/sh", "sh", "/bin/bash", "bash"}
        and argv[1] in {"-c", "-lc"}
    )


_SHELL_RAW_TOKENS = {
    "!",
    ";",
    "&&",
    "||",
    "|",
    "|&",
    "&",
    "(",
    ")",
    "{",
    "}",
    "[[",
    "]]",
    ">",
    ">>",
    ">|",
    "<",
    "<<",
    "<<-",
    "<<<",
    "<&",
    ">&",
    ";;",
    ";&",
    ";;&",
}

_SHELL_VAR_TOKEN_RE = re.compile(r"^\$[A-Za-z_][A-Za-z0-9_]*$|^\$\{[^}]+\}$")


def _join_shell_tokens(tokens: list[str]) -> str:
    """
    Rebuild a shell payload from tokenized compose output.

    We keep shell operators raw so syntax like `if ! ...; then` survives, but
    still quote normal arguments that contain spaces or comment markers.
    """
    parts: list[str] = []
    for token in tokens:
        if token in _SHELL_RAW_TOKENS or _SHELL_VAR_TOKEN_RE.fullmatch(token):
            parts.append(token)
        else:
            parts.append(shlex.quote(token))
    return " ".join(parts)


def _collapse_shell_form(argv: list[str]) -> list[str]:
    """
    Canonicalize tokenized shell-form argv back into a single shell string.

    compose config may flatten shell-form commands/entrypoints into
    multiple argv items. When we later re-wrap them, /bin/sh -c must receive
    one shell payload, otherwise the shell sees tokenized words and breaks on
    characters like # or !.
    """
    if len(argv) > 3 and _is_shell_form(argv):
        return [argv[0], argv[1], _join_shell_tokens(argv[2:])]
    return argv


def _shell_payload(argv: list[str]) -> str:
    """
    Convert argv into a single shell payload string.

    If argv is already shell-form, strip the launcher and keep the actual
    command string. Otherwise join the argv safely for shell consumption.
    """
    if _is_shell_form(argv):
        if len(argv) == 3:
            return argv[2]
        return _join_shell_tokens(argv[2:])
    if len(argv) == 1:
        return argv[0]
    return _join_shell_tokens(argv)


def normalize_cmd(value: Any) -> list[str]:
    """
    Normalize a compose 'command' value into exec-form list[str].

    Supported:
      - list[str] => as-is
      - string    => shell-form: ["/bin/sh", "-lc", "<string>"]
      - None      => []
    """
    if value is None:
        return []
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return _collapse_shell_form(value)
    if isinstance(value, str) and value.strip():
        return ["/bin/sh", "-lc", value]
    die(f"Unsupported command type in compose config: {type(value)}")
    return None


def normalize_entrypoint(value: Any) -> list[str]:
    """
    Normalize a compose 'entrypoint' value into exec-form list[str].

    Supported:
      - list[str] => as-is
      - string    => shell-form: ["/bin/sh", "-lc", "<string>"]
      - None      => []
    """
    if value is None:
        return []
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return _collapse_shell_form(value)
    if isinstance(value, str) and value.strip():
        return ["/bin/sh", "-lc", value]
    die(f"Unsupported entrypoint type in compose config: {type(value)}")
    return None


def escape_compose_vars(argv: list[str]) -> list[str]:
    """
    Docker Compose interpolates $FOO and ${FOO} in YAML strings on the HOST side
    (compose config time). That breaks container-side expansion (e.g. sh -lc 'exec "$FOO"')
    when the host env var is unset, because it becomes exec "".

    Compose escaping rule:
      - $$ => literal $ (no interpolation)

    Therefore: replace every "$" with "$$" in exec-form argv strings that we write into
    compose override YAML (entrypoint/command).
    """
    return [s.replace("$", "$$") for s in argv]


def docker_image_inspect(
    image: str, *, cwd: Path, env: dict[str, str]
) -> tuple[list[str], list[str]]:
    """
    Return (Entrypoint, Cmd) for the given image in exec-form list[str].
    """
    rc, out, err = run(["docker", "image", "inspect", image], cwd=cwd, env=env)
    if rc != 0:
        die(f"container image inspect failed for '{image}' (rc={rc}): {err.strip()}")

    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        die(f"container image inspect returned invalid JSON for '{image}': {e}")

    if not isinstance(data, list) or not data:
        die(f"container image inspect returned empty result for '{image}'")

    cfg = data[0].get("Config")
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        die(f"container image inspect missing/invalid Config for '{image}'")

    ep = cfg.get("Entrypoint")
    cmd = cfg.get("Cmd")

    if ep is None:
        ep_list: list[str] = []
    elif isinstance(ep, list) and all(isinstance(x, str) for x in ep):
        ep_list = ep
    else:
        die(f"Unexpected Entrypoint type for image '{image}': {type(ep)}")

    if cmd is None:
        cmd_list: list[str] = []
    elif isinstance(cmd, list) and all(isinstance(x, str) for x in cmd):
        cmd_list = cmd
    else:
        die(f"Unexpected Cmd type for image '{image}': {type(cmd)}")

    return ep_list, cmd_list


def docker_image_exists(image: str, *, cwd: Path, env: dict[str, str]) -> bool:
    rc, _out, _err = run(["docker", "image", "inspect", image], cwd=cwd, env=env)
    return rc == 0


TIMEOUT_RC = 124


def docker_image_has_bin_sh(
    image: str, *, cwd: Path, env: dict[str, str]
) -> bool | None:
    """Best-effort detection whether the image provides /bin/sh."""
    rc, _out, _err = run(
        ["docker", "run", "--rm", "--entrypoint", "/bin/sh", image, "-c", "exit 0"],
        cwd=cwd,
        env=env,
        timeout=60,
        capture=False,
    )
    if rc == 0:
        return True
    if rc == TIMEOUT_RC:
        return None
    return False


ImageMeta = tuple[bool, list[str], list[str], bool | None]


def _gather_one_image(image: str, *, cwd: Path, env: dict[str, str]) -> ImageMeta:
    rc, out, _err = run(
        ["docker", "image", "inspect", image], cwd=cwd, env=env, timeout=90
    )
    if rc != 0:
        return (False, [], [], None if rc == TIMEOUT_RC else False)
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return (False, [], [], False)
    cfg = data[0].get("Config") if isinstance(data, list) and data else None
    cfg = cfg if isinstance(cfg, dict) else {}
    ep = cfg.get("Entrypoint")
    cmd = cfg.get("Cmd")
    ep_list = ep if isinstance(ep, list) and all(isinstance(x, str) for x in ep) else []
    cmd_list = (
        cmd if isinstance(cmd, list) and all(isinstance(x, str) for x in cmd) else []
    )
    has_sh = docker_image_has_bin_sh(image, cwd=cwd, env=env)
    return (True, ep_list, cmd_list, has_sh)


def gather_image_meta(
    images: list[str], *, cwd: Path, env: dict[str, str]
) -> dict[str, ImageMeta]:
    """Gather (exists, entrypoint, cmd, has_sh) per unique image, concurrently
    — the per-image docker reads dominate the inject and must not run serially
    under DiD latency or they blow the handler timeout for many-service apps."""
    if not images:
        return {}
    workers = min(8, len(images))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_gather_one_image, image, cwd=cwd, env=env): image
            for image in images
        }
        return {futures[f]: f.result() for f in as_completed(futures)}


def _has_build(svc: dict[str, Any]) -> bool:
    return isinstance(svc.get("build"), (dict, str))


def _find_builder_service_for_image(*, image: str, services: dict[str, Any]) -> str:
    """
    If multiple services reference the same locally-built image, only one of them
    may define `build:`. This function finds that builder service.
    """
    wanted = (image or "").strip()
    if not wanted:
        return ""
    for name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        if str(svc.get("image") or "").strip() == wanted and _has_build(svc):
            return name
    return ""


def ensure_image_available(
    *,
    service_name: str,
    svc: dict[str, Any],
    image: str,
    services: dict[str, Any],
    service_to_compose_cmd: dict[str, list[str]],
    compose_base_cmd: list[str],
    cwd: Path,
    env: dict[str, str],
) -> None:
    """
    Ensure the referenced image exists locally.

    Strategy:
      1) If container image inspect works -> OK
      2) Else:
         - If THIS service has 'build' -> run `compose ... build <service>`
         - Else if another service builds the SAME image -> build that builder service
         - Otherwise -> run `compose ... pull <service>`
    """
    img = (image or "").strip()
    if not img:
        die(f"ensure_image_available: empty image for service '{service_name}'")

    if docker_image_exists(img, cwd=cwd, env=env):
        return

    if _has_build(svc):
        run_checked(
            [*compose_base_cmd, "build", service_name],
            cwd=cwd,
            env=env,
            label=f"compose build {service_name}",
        )
    else:
        builder = _find_builder_service_for_image(image=img, services=services)
        if builder:
            builder_cmd = service_to_compose_cmd.get(builder)
            if not builder_cmd:
                builder_cmd = compose_base_cmd
            run_checked(
                [*builder_cmd, "build", builder],
                cwd=cwd,
                env=env,
                label=f"compose build {builder} (builder for image {img})",
            )
        else:
            run_checked(
                [*compose_base_cmd, "pull", service_name],
                cwd=cwd,
                env=env,
                label=f"compose pull {service_name}",
            )

    if not docker_image_exists(img, cwd=cwd, env=env):
        die(
            f"Image '{img}' for service '{service_name}' is still missing after build/pull. "
            "If this is a locally-built image, ensure one service defines both `build:` and `image:`."
        )


def _extract_compose_files(parts: list[str], *, cwd: Path) -> list[Path]:
    """
    Extract compose file paths from args like: ['-f','a.yml','-f','b.yml'].
    Resolve relative paths against cwd.
    """
    files: list[Path] = []
    i = 0
    while i < len(parts):
        if parts[i] == "-f":
            if i + 1 >= len(parts):
                die("Invalid --compose-files: '-f' without a filename")
            p = Path(parts[i + 1])
            if not p.is_absolute():
                p = cwd / p
            files.append(p)
            i += 2
        else:
            i += 1
    if not files:
        die("No compose files found in --compose-files (expected -f <file> ...)")
    return files


def _discover_profiles_from_files(compose_files: list[Path]) -> list[str]:
    """
    Discover all profile names referenced by any service across the compose files.
    """
    profiles: set[str] = set()
    for f in compose_files:
        if not f.exists():
            die(f"Compose file does not exist: {f}")
        try:
            doc = (
                yaml.safe_load(f.read_text(encoding="utf-8"))  # nocheck: direct-yaml
                or {}
            )
        except Exception as e:
            die(f"Failed to parse compose file '{f}': {e}")

        if not isinstance(doc, dict):
            continue
        services = doc.get("services")
        if not isinstance(services, dict):
            continue

        for svc in services.values():
            if not isinstance(svc, dict):
                continue
            p = svc.get("profiles")
            if isinstance(p, str) and p.strip():
                profiles.add(p.strip())
            elif isinstance(p, list):
                for x in p:
                    if isinstance(x, str) and x.strip():
                        profiles.add(x.strip())

    return sorted(profiles)


def _compose_base_cmd(*, project: str, parts: list[str], env_file: str) -> list[str]:
    cmd: list[str] = ["docker", "compose", "-p", project, *parts]
    if env_file.strip():
        cmd += ["--env-file", env_file.strip()]
    return cmd


def _compose_cmd_with_profile(base_cmd: list[str], profile: str) -> list[str]:
    """
    Add a --profile <name> (global compose flag) to an existing base cmd.
    Expected base cmd: ['compose', ...]
    """
    if len(base_cmd) < 2 or base_cmd[0] != "docker" or base_cmd[1] != "compose":
        die(f"Invalid compose base cmd: {base_cmd}")

    # Insert after the compose wrapper prefix
    return [*base_cmd[:2], "--profile", profile, *base_cmd[2:]]


def _load_services_via_config(
    *,
    compose_cmd: list[str],
    cwd: Path,
    env: dict[str, str],
    label: str,
) -> dict[str, Any]:
    rc, out, err = run([*compose_cmd, "config"], cwd=cwd, env=env)
    if rc != 0:
        die(f"compose config failed for {label} (rc={rc}): {err.strip()}")

    doc = parse_yaml(out, f"compose config output ({label})")
    services = doc.get("services")
    if not isinstance(services, dict) or not services:
        return {}
    return services


def render_override(
    services: dict[str, Any],
    service_to_compose_cmd: dict[str, list[str]],
    *,
    cwd: Path,
    env: dict[str, str],
    ca_host: str,
    wrapper_host: str,
    trust_name: str,
    wrap: bool = True,
) -> dict[str, Any]:
    """
    Generate a compose override that injects CA trust into every service by:
      - always: mounting CA cert + wrapper script, setting CA env vars + useful TLS env fallbacks
      - optionally: using wrapper entrypoint when /bin/sh exists in the image:
            - override entrypoint to wrapper script
            - set command to the effective original exec-form (entrypoint+cmd)
        This avoids breaking distroless images that do not provide /bin/sh.

    Args:
      wrap: when False, emit ONLY volumes + environment and never the
        entrypoint/command wrapper. `docker stack deploy` does not un-escape
        the `$$` that the wrapper's command argv carries, so the wrapper is
        swarm-incompatible; swarm callers pass wrap=False and rely on the
        SSL_CERT_FILE/CURL_CA_BUNDLE/NODE_EXTRA_CA_CERTS env + the CA mount.

    IMPORTANT:
      Docker Compose interpolates $VARS in YAML strings on the host.
      We escape any $ in the command argv with $$ so container-side expansion works.
    """
    # Container-internal CA-injection paths bind-mounted from the host.
    # Not user-controllable; well-known by the role's compose template.
    ca_container = "/tmp/infinito/ca/root-ca.crt"  # noqa: S108
    wrapper_container = "/tmp/infinito/bin/with-ca-trust.sh"  # noqa: S108

    out_services: dict[str, Any] = {}

    image_meta = gather_image_meta(
        sorted(
            {
                svc["image"].strip()
                for svc in services.values()
                if isinstance(svc, dict)
                and isinstance(svc.get("image"), str)
                and svc["image"].strip()
            }
        ),
        cwd=cwd,
        env=env,
    )

    for name, svc in services.items():
        if not isinstance(svc, dict):
            die(f"Service '{name}' must be a mapping in compose config")

        override_svc: dict[str, Any] = {
            "volumes": [
                f"{ca_host}:{ca_container}:ro",
                f"{wrapper_host}:{wrapper_container}:ro",
            ],
            "environment": {
                "CA_TRUST_CERT": ca_container,
                "CA_TRUST_NAME": trust_name,
                "SSL_CERT_FILE": ca_container,
                "REQUESTS_CA_BUNDLE": ca_container,
                "CURL_CA_BUNDLE": ca_container,
                "NODE_EXTRA_CA_CERTS": ca_container,
            },
        }

        if not wrap:
            out_services[name] = override_svc
            continue

        svc_ep = normalize_entrypoint(svc.get("entrypoint"))
        svc_cmd = normalize_cmd(svc.get("command"))

        image = svc.get("image")
        if not isinstance(image, str) or not image.strip():
            # If there is no image, we can only wrap if effective command is explicitly defined
            if not svc_ep and not svc_cmd:
                die(
                    f"Service '{name}' has no image and no entrypoint/command in composed config"
                )
            img_ep, img_cmd = [], []
            img_name = ""
            has_sh = False
        else:
            img_name = image.strip()
            _exists, raw_ep, raw_cmd, sh_state = image_meta.get(
                img_name, (False, [], [], None)
            )
            has_sh = sh_state is not False
            img_ep = normalize_entrypoint(raw_ep)
            img_cmd = normalize_cmd(raw_cmd)

        final_ep = svc_ep or img_ep
        final_cmd = svc_cmd or img_cmd

        if _is_shell_form(final_ep):
            final_cmd = [_shell_payload(final_cmd)]

        effective_cmd = final_ep + final_cmd

        if has_sh and effective_cmd:
            override_svc["entrypoint"] = [wrapper_container]
            override_svc["command"] = escape_compose_vars(effective_cmd)

        out_services[name] = override_svc

    return {"services": out_services}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate compose CA trust override via compose config"
    )
    ap.add_argument("--chdir", required=True, help="Compose instance directory")
    ap.add_argument("--project", required=True, help="Compose project name (-p)")
    ap.add_argument(
        "--compose-files",
        required=True,
        help='Compose files args string like: "-f a.yml -f b.yml"',
    )
    ap.add_argument("--env-file", default="", help="Optional env file path")
    ap.add_argument(
        "--out", required=True, help="Output filename (relative to --chdir or absolute)"
    )
    ap.add_argument(
        "--ca-host", required=True, help="Host path to CA cert (bind-mounted)"
    )
    ap.add_argument(
        "--wrapper-host",
        required=True,
        help="Host path to wrapper script (bind-mounted)",
    )
    ap.add_argument(
        "--trust-name",
        required=True,
        help="Trust anchor name for CA installation inside containers (CA_TRUST_NAME)",
    )
    ap.add_argument(
        "--no-wrapper",
        action="store_true",
        help=(
            "Emit only volumes + environment, never the entrypoint/command "
            "wrapper. Use for `docker stack deploy`, which does not un-escape "
            "the wrapper command's $$ and would run the literal $$VAR."
        ),
    )
    args = ap.parse_args()

    cwd = Path(args.chdir)
    if not cwd.exists() or not cwd.is_dir():
        die(f"--chdir must be an existing directory: {cwd}")

    ca_host = str(args.ca_host).strip()
    wrapper_host = str(args.wrapper_host).strip()
    trust_name = str(args.trust_name).strip()

    if not ca_host:
        die("--ca-host must be non-empty")
    if not wrapper_host:
        die("--wrapper-host must be non-empty")
    if not trust_name:
        die("--trust-name must be non-empty")

    env = dict(os.environ)

    env_file = str(args.env_file).strip()
    if env_file:
        ef = Path(env_file)
        if not ef.is_absolute():
            ef = cwd / ef
        if not ef.exists():
            die(f"--env-file was provided but file does not exist: {ef}")
        env_file = str(ef)

    parts = str(args.compose_files).strip().split()
    if not parts:
        die("--compose-files must be non-empty")

    compose_files = _extract_compose_files(parts, cwd=cwd)

    merged_services: dict[str, Any] = {}
    service_to_compose_cmd: dict[str, list[str]] = {}

    if args.no_wrapper:
        # Avoid `docker compose config` here: its dotenv parser aborts on swarm
        # env files with verbatim special-char secrets. wrap=False needs only names.
        for cf in compose_files:
            doc = parse_yaml(
                cf.read_text(encoding="utf-8"),  # nocheck: direct-yaml
                f"compose file ({cf})",
            )
            svcs = doc.get("services")
            if isinstance(svcs, dict):
                for svc_name, svc_def in svcs.items():
                    merged_services.setdefault(svc_name, svc_def)
    else:
        compose_base_cmd = _compose_base_cmd(
            project=str(args.project),
            parts=parts,
            env_file=env_file or "",
        )
        profiles = _discover_profiles_from_files(compose_files)

        default_services = _load_services_via_config(
            compose_cmd=compose_base_cmd,
            cwd=cwd,
            env=env,
            label="default",
        )
        for svc_name, svc_def in default_services.items():
            merged_services[svc_name] = svc_def
            service_to_compose_cmd[svc_name] = compose_base_cmd

        for p in profiles:
            cmd_p = _compose_cmd_with_profile(compose_base_cmd, p)
            prof_services = _load_services_via_config(
                compose_cmd=cmd_p,
                cwd=cwd,
                env=env,
                label=f"profile:{p}",
            )
            for svc_name, svc_def in prof_services.items():
                if svc_name not in merged_services:
                    merged_services[svc_name] = svc_def
                    service_to_compose_cmd[svc_name] = cmd_p

    if merged_services:
        override_doc = render_override(
            merged_services,
            service_to_compose_cmd,
            cwd=cwd,
            env=env,
            ca_host=ca_host,
            wrapper_host=wrapper_host,
            trust_name=trust_name,
            wrap=not args.no_wrapper,
        )
    else:
        override_doc = {"services": {}}

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = cwd / out_path

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        text = yaml.safe_dump(  # nocheck: direct-yaml
            override_doc, sort_keys=True, default_flow_style=False
        )
        out_path.write_text(text, encoding="utf-8")
    except Exception as e:
        die(f"Failed to write output file {out_path}: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
