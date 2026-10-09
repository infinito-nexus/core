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
API_KEY = "toolsLaneTestKeyNotASecret0000000000"
LIBRETRANSLATE_ROLE = "svc-ai-libretranslate-engine"
S1_ROLE = "svc-ai-s1"
LANE_SERVICE = "tools"
PROBE_TIMEOUT_SECONDS = 10


def models_dir() -> str:
    """Return the node-local directory the lane keeps its models in.

    Reads the same value ``compose/tools.override.yml`` mounts into the
    runner, so a bind the inventory writes resolves to the host directory
    rather than to something inside the runner that a rebuild discards.
    """
    from utils.env.handlers.infinito.tools.models import KEY, default

    return (os.environ.get(KEY) or "").strip() or default()


def lane_url(root: Path, role: str, service_key: str) -> str:
    """Return the URL a container of the compose stack reaches a lane service on.

    The lane runs its services in a docker daemon of its own, inside the
    runner container. The inventory pins ``DOCKER_BIND_HOST=0.0.0.0`` so
    their ports are open on the runner's own interface, which the group_vars
    default would not do (see ``inventories/development/tools.yml.j2``). The
    runner and the rest of the stack share the compose network, which makes
    the runner's service name the address to use. The host instead reaches
    only the ports the runner republishes through ``compose/tools.override.yml``.

    Args:
        root: repository root.
        role: application id owning the service.
        service_key: key under ``meta/services.yml``.

    Returns:
        ``http://<lane service>:<local http port>``.
    """
    services = load_yaml(root / "roles" / role / ROLE_FILE_META_SERVICES)
    port = services[service_key]["ports"]["local"]["http"]
    return f"http://{LANE_SERVICE}:{port}"


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


def _answers(url: str) -> bytes | None:
    """Return what ``url`` served, or None when it did not answer.

    Args:
        url: absolute URL to read.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_SECONDS) as response:  # noqa: S310 - the URL is this repository's own service definition
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


def serving(root: Path, load_only: list[str]) -> bool:
    """Return whether the lane's engine already carries everything asked of it.

    Reachability alone is not enough: the engine answers as soon as it has
    booted, with whatever subset of models it found, and a run that then waits
    for the rest waits forever. The language set it reports is compared
    against what the lane pins.

    Only the engine is judged. It is the one lane service the runner
    republishes to the host, and the expensive one: a deploy reinstalls its
    whole model selection and restarts it. The lane is deployed as a unit, so
    an engine that carries the full selection is one the deploy already
    finished. A sibling that is down anyway reports itself, because each check
    states which address failed to answer.

    Args:
        root: repository root.
        load_only: the language codes the lane pins.
    """
    import json

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

    Args:
        root: repository root.
        roles: application ids to deploy.

    Raises:
        RuntimeError: a deploy already holds the container stack this one
            would touch.
    """
    from utils.i18n.libretranslate import baked_languages, deploy, deploying

    if serving(root, baked_languages(root)):
        print(
            f"tools lane already serves {', '.join(roles)}; not deploying", flush=True
        )
        return

    if deploying(root):
        raise RuntimeError(
            "A deploy is running; it shares the container stack the tools lane "
            "would touch. Wait for it to finish and re-run. The running deploy "
            "is left untouched."
        )
    print(f"tools lane deploying {', '.join(roles)}", flush=True)
    deploy(root, roles=roles)


def main(argv: list[str] | None = None) -> int:
    """Bring the lane up for ``make test-oracle``, reporting why when it cannot.

    Exits 0 even when the lane stays down, because the checks that need it say
    so themselves; a deploy that is already running is a reason to leave the
    stack alone, not to fail the target.

    Args:
        argv: application ids, defaulting to every role the lane serves.
    """
    import argparse

    from utils import PROJECT_ROOT

    default_roles = [LIBRETRANSLATE_ROLE, S1_ROLE]
    parser = argparse.ArgumentParser(description="Bring the tools lane up.")
    parser.add_argument("roles", nargs="*", default=default_roles)
    args = parser.parse_args(argv)
    roles = tuple(args.roles) or tuple(default_roles)
    try:
        ensure(Path(PROJECT_ROOT), roles)
    except (RuntimeError, OSError, KeyError, subprocess.CalledProcessError) as down:
        print(f"tools lane not brought up: {down!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
