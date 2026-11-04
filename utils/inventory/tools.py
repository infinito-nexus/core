"""The tools lane: the host vars its services deploy with, and bringing it up.

The lane holds the toolchain services the repository's own targets and tests
call: the translation engine behind the ``i18n`` targets, and the System One
classifier the semantic suite asks for a verdict. A caller names the roles it
needs and gets them running, so a check is never skipped merely because
nothing happened to be up.

The template carries Ansible expressions the deploy resolves later, so it is
rendered with the Ansible parts inside ``raw`` blocks; everything this module
fills is an ordinary Jinja expression. The rendered file lands beside the
template so the runner's bind mount of the repository exposes it inside the
container.

Nothing here deploys a cache: the runner extends ``compose.cache-consumer.yml``
from the outer stack, so its image pulls already traverse ``registry-cache``
and its package and model downloads resolve to ``package-cache-frontend``
through that file's ``extra_hosts``.

System One authenticates its callers, and its key is an
``algorithm: alphanumeric`` credential the provisioner would otherwise
generate into a vault the caller cannot read back. :data:`API_KEY` pins one
instead, so the lane and the checks that call it agree without reading a vault
or passing a secret on a command line. It is a fixed literal because the lane
serves the repository's own tooling on a developer machine and reaches no
deployment that holds data, the same standing as the dummy authorized key the
template already carries. Never reuse it anywhere a real caller could reach.

:data:`LITELLM_KEY` pins the model gateway's master key for the same reason
and under the same standing. A deployment hands each consumer a virtual key
instead, which is what the role's secret description asks for; the oracle
judge is not a deployed consumer and has no vault to read one from.

The lane pins its own model in the template, rather than taking the
repository's ``AI_LOCAL_MODELS`` default: the oracle needs a judge that can
tell a faithful rendering from an unrelated text, a demand no deployment
makes. :data:`LANE_MODEL_ALIAS` repeats that one name here because the
readiness probe compares it against what the gateway actually serves, and
the rendered inventory is written by the deploy this probe runs before. The
two are held together by a test that renders the template.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_META_SERVICES

TEMPLATE = Path("inventories") / "development" / "tools.yml.j2"
RENDERED = Path("inventories") / "development" / "tools.rendered.yml"
ADDRESS = Path("inventories") / "development" / "tools.address"
API_KEY = "toolsLaneTestKeyNotASecret0000000000"
LITELLM_KEY = "toolsLaneLiteLlmMasterKeyNotASecret000000000000000000"
LIBRETRANSLATE_ROLE = "svc-ai-libretranslate-engine"
S1_ROLE = "svc-ai-s1"
LITELLM_ROLE = "svc-ai-litellm"
OLLAMA_ROLE = "svc-ai-ollama"
GATEWAY_ROLE = "web-svc-translate"
LANE_SERVICE = "tools"
LANE_MODEL_ALIAS = "qwen2.5:3b"
PROBE_TIMEOUT_SECONDS = 10


def models_dir() -> str:
    """Return the node-local directory the lane keeps its models in.

    Reads the same value ``compose/tools.override.yml`` mounts into the
    runner, so a bind the inventory writes resolves to the host directory
    rather than to something inside the runner that a rebuild discards.
    """
    from utils.env.handlers.infinito.tools.models import KEY, default

    return (os.environ.get(KEY) or "").strip() or default()


def lane_ip(root: Path) -> str:
    """Return the runner's address inside the stack's own subnet, or ''.

    Must run on the host: it asks this machine's docker daemon, which the
    stack's containers cannot reach.

    The runner answers to several addresses, one per network it was ever
    brought up on, and only the one inside ``INFINITO_SUBNET`` is the network
    the rest of the stack sits on.

    Args:
        root: repository root.
    """
    import ipaddress
    import json

    from utils.i18n.libretranslate import environment, lane_container

    env = environment(root)
    found = subprocess.run(
        [
            "docker",
            "inspect",
            lane_container(env),
            "--format",
            "{{json .NetworkSettings.Networks}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if found.returncode != 0:
        return ""
    try:
        subnet = ipaddress.ip_network(env["INFINITO_SUBNET"])
        networks = json.loads(found.stdout)
    except (KeyError, ValueError):
        return ""
    for entry in networks.values():
        address = (entry or {}).get("IPAddress") or ""
        if address and ipaddress.ip_address(address) in subnet:
            return address
    return ""


def lane_address(root: Path) -> str:
    """Return the address the stack's containers reach the lane on.

    Args:
        root: repository root.
    """
    path = root / ADDRESS
    if not path.is_file():
        return LANE_SERVICE
    return (
        path.read_text(  # nocheck: cache-read - every lane bring-up rewrites this file and utils.cache.files.read_text is an lru_cache without mtime invalidation
            encoding="utf-8"
        ).strip()
        or LANE_SERVICE
    )


def lane_url(root: Path, role: str, service_key: str) -> str:
    """Return the URL a container of the compose stack reaches a lane service on.

    The lane runs its services in a docker daemon of its own, inside the
    runner container. The inventory pins ``DOCKER_BIND_HOST=0.0.0.0`` so
    their ports are open on the runner's own interface, which the group_vars
    default would not do (see ``inventories/development/tools.yml.j2``). The
    host instead reaches only the ports the runner republishes through
    ``compose/tools.override.yml``.

    The address is the runner's numeric one, written by the bring-up. The
    stack's containers resolve names through its CoreDNS, which never learns
    a compose service name, so ``tools`` answered nowhere inside them and
    every check that asked the lane from there skipped itself instead.

    Args:
        root: repository root.
        role: application id owning the service.
        service_key: key under ``meta/services.yml``.

    Returns:
        ``http://<lane address>:<local http port>``.
    """
    services = load_yaml(root / "roles" / role / ROLE_FILE_META_SERVICES)
    port = services[service_key]["ports"]["local"]["http"]
    return f"http://{lane_address(root)}:{port}"


def host_url(root: Path, role: str, service_key: str) -> str:
    """Return the URL the host reaches a lane service on.

    The runner republishes the lane's ports through
    ``compose/tools.override.yml``, so a caller on the host uses the bind
    address rather than the compose service name :func:`lane_url` gives a
    sibling container.

    Args:
        root: repository root.
        role: application id owning the service.
        service_key: key under ``meta/services.yml``.
    """
    from utils.i18n.libretranslate import environment

    services = load_yaml(root / "roles" / role / ROLE_FILE_META_SERVICES)
    port = services[service_key]["ports"]["local"]["http"]
    return f"http://{environment(root)['INFINITO_BIND_IP']}:{port}"


def _answers(url: str, api_key: str = "") -> bytes | None:
    """Return what ``url`` served, or None when it did not answer.

    Args:
        url: absolute URL to read.
        api_key: sent as a bearer token, for a route that authenticates its
            callers. A 401 reads as no answer, which is what it means here:
            the service is up but holds a key the checks cannot use, and a
            lane in that state has to be deployed again rather than reused.
    """
    import urllib.error
    import urllib.request

    request = urllib.request.Request(url)  # noqa: S310 - the URL is this repository's own service definition
    if api_key:
        request.add_header("Authorization", f"Bearer {api_key}")
    try:
        with urllib.request.urlopen(  # noqa: S310 - the URL is this repository's own service definition
            request, timeout=PROBE_TIMEOUT_SECONDS
        ) as response:
            return response.read()
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _base_subtag(code: str) -> str:
    """Return the language subtag of ``code``, dropping any script or region.

    The lane pins ``zh`` and the engine reports the same language as
    ``zh-Hans``. Comparing the codes as given never matches, which would leave
    the readiness check permanently false.

    Args:
        code: an ISO 639-1 code, optionally with a subtag.
    """
    return code.split("-", 1)[0].strip().lower()


def _litellm_serves_the_named_model(root: Path) -> bool:
    """Return whether the model gateway answers with the catalogue's model.

    Reachability is not enough twice over. The route authenticates, so a
    gateway holding a key these checks cannot use looks healthy from outside
    and refuses every call they make. And a lane brought up before
    ``AI_LOCAL_MODELS`` named a different model keeps serving the old one,
    which no probe of liveliness can see.

    Args:
        root: repository root.
    """
    import json

    alias = _named_model()
    body = _answers(f"{host_url(root, LITELLM_ROLE, 'litellm')}/models", LITELLM_KEY)
    if body is None or not alias:
        return False
    try:
        served = {entry.get("id") for entry in json.loads(body).get("data") or []}
    except (ValueError, AttributeError, TypeError):
        return False
    return alias in served


def _named_model() -> str:
    """Return the alias the lane's model server is expected to serve."""
    return LANE_MODEL_ALIAS


def _gateway_covers_the_catalogs(root: Path) -> bool:
    """Return whether the gateway offers every language the catalogs name.

    A gateway that answers is not a gateway that routes: its ``/languages``
    is the union over its backends, so one whose chat backend declares no
    pairs advertises the engine's 47 codes and nothing else. The translation
    run waits on exactly this list, so a lane left in that state is not
    serving however healthy each container looks.

    Args:
        root: repository root.
    """
    import json

    from utils.i18n.languages import (
        DOMAINS,
        SOURCE_LANGUAGE,
        domain_languages,
        load_languages,
    )

    body = _answers(f"{host_url(root, GATEWAY_ROLE, 'translate')}/languages")
    if body is None:
        return False
    try:
        served = {
            entry["code"]: set(entry["targets"]) for entry in json.loads(body)
        }.get(SOURCE_LANGUAGE, set())
    except (ValueError, KeyError, TypeError):
        return False
    languages = load_languages(root)
    wanted = {
        code for domain in DOMAINS for code in domain_languages(languages, domain)
    }
    return wanted <= served


def serving(root: Path, load_only: list[str], roles: tuple[str, ...]) -> bool:
    """Return whether every lane role asked for already answers.

    Reachability alone is not enough for the engine: it answers as soon as it
    has booted, with whatever subset of models it found, and a run that then
    waits for the rest waits forever. The language set it reports is compared
    against what the lane pins.

    Judging the engine alone made ``make test-oracle`` vacuous: ``make i18n``
    deploys the engine on its own, so a lane whose engine served counted as up
    while System One was down, and the oracle suite skipped itself to a green
    exit. Every role the caller names is probed, which is why the runner
    republishes System One's port too.

    Args:
        root: repository root.
        load_only: the language codes the lane pins.
        roles: the application ids the caller wants running.
    """
    import json

    if S1_ROLE in roles and _answers(f"{host_url(root, S1_ROLE, 's1')}/health") is None:
        return False
    if LITELLM_ROLE in roles and not _litellm_serves_the_named_model(root):
        return False
    if GATEWAY_ROLE in roles and not _gateway_covers_the_catalogs(root):
        return False
    if LIBRETRANSLATE_ROLE not in roles:
        return True
    body = _answers(
        f"{host_url(root, LIBRETRANSLATE_ROLE, 'libretranslate-engine')}/languages"
    )
    if body is None:
        return False
    try:
        served = {_base_subtag(entry["code"]) for entry in json.loads(body)}
    except (ValueError, KeyError, TypeError):
        return False
    return {_base_subtag(code) for code in load_only} <= served


def render(root: Path, load_only: list[str]) -> Path:
    """Write the tools lane host vars and return the rendered file.

    Args:
        root: repository root.
        load_only: every language code the lane's image prefetches models for.
            Pinning the whole set keeps the build ARG constant, so the prefetch
            layer is not rebuilt once per batch.

    Returns:
        The rendered file.
    """
    template_path = root / TEMPLATE
    env = Environment(
        loader=FileSystemLoader(str(template_path.parent)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        variable_start_string="[[",
        variable_end_string="]]",
        block_start_string="[%",
        block_end_string="%]",
        autoescape=False,  # noqa: S701 - YAML output, HTML escaping would corrupt it
    )
    body = env.get_template(template_path.name).render(
        load_only=sorted(load_only),
        s1_api_key=API_KEY,
        litellm_master_key=LITELLM_KEY,
        models_dir=models_dir(),
    )
    rendered = root / RENDERED
    rendered.write_text(body, encoding="utf-8")
    return rendered


def ensure(root: Path, roles: tuple[str, ...]) -> None:
    """Bring the named lane roles up, unless they already serve.

    Must run on the host: the lane is deployed with ``docker compose``, whose
    bind mounts name host paths, so the same call from inside a container of
    the stack resolves them against the wrong filesystem.

    A deploy installs the whole model selection and restarts the engine onto
    it, which costs minutes. Every caller of this function wants a lane that
    answers, not a lane that was just rebuilt, so one that already answers
    with everything asked of it is left alone.

    Either way the runner's address is written down, because a container of
    the stack cannot ask docker for it and the runner takes a new one on
    every restart.

    Args:
        root: repository root.
        roles: application ids to deploy.

    Raises:
        RuntimeError: a deploy already holds the container stack this one
            would touch.
    """
    from utils.i18n.libretranslate import baked_languages, deploy, deploying

    if serving(root, baked_languages(root), roles):
        print(
            f"tools lane already serves {', '.join(roles)}; not deploying", flush=True
        )
        _remember_address(root)
        return

    if deploying(root):
        raise RuntimeError(
            "A deploy is running; it shares the container stack the tools lane "
            "would touch. Wait for it to finish and re-run. The running deploy "
            "is left untouched."
        )
    print(f"tools lane deploying {', '.join(roles)}", flush=True)
    deploy(root, roles=roles)
    _remember_address(root)


def _remember_address(root: Path) -> None:
    """Write the runner's address where a container of the stack reads it."""
    address = lane_ip(root)
    if address:
        (root / ADDRESS).write_text(f"{address}\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Bring the lane up for ``make test-oracle``, reporting why when it cannot.

    Only a deploy that is already running exits 0: it holds the stack this
    one would touch, and leaving it alone is the right answer. Every other
    way of not bringing the lane up exits 1, including a deploy that crashed
    and a deploy that ran and left a role silent. The suite skips itself when
    the lane is down, and a skip is a green exit, so a target that returned 0
    here would report a verdict it never reached.

    Args:
        argv: application ids, defaulting to every role the lane serves.
    """
    import argparse

    from utils import PROJECT_ROOT
    from utils.i18n.libretranslate import baked_languages

    default_roles = [
        LIBRETRANSLATE_ROLE,
        S1_ROLE,
        OLLAMA_ROLE,
        LITELLM_ROLE,
        GATEWAY_ROLE,
    ]
    parser = argparse.ArgumentParser(description="Bring the tools lane up.")
    parser.add_argument("roles", nargs="*", default=default_roles)
    args = parser.parse_args(argv)
    roles = tuple(args.roles) or tuple(default_roles)
    root = Path(PROJECT_ROOT)
    try:
        ensure(root, roles)
    except RuntimeError as held:
        print(f"tools lane left alone: {held!r}")
        return 0
    except (OSError, KeyError, subprocess.CalledProcessError) as down:
        print(f"tools lane not brought up: {down!r}")
        return 1
    if not serving(root, baked_languages(root), roles):
        print(f"tools lane deployed but {', '.join(roles)} still do not all answer")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
