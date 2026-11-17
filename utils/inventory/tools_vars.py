"""The tools lane's host vars: the inventory its services deploy with.

The template carries Ansible expressions the deploy resolves later, so it is
rendered with the Ansible parts inside ``raw`` blocks; everything this module
fills is an ordinary Jinja expression. The rendered file lands beside the
template so the runner's bind mount of the repository exposes it inside the
container.

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
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.env.handlers.infinito.cache.paths import BASE_KEY
from utils.env.handlers.infinito.tools.models import KEY as MODELS_KEY

if TYPE_CHECKING:
    from collections.abc import Mapping

TEMPLATE = Path("inventories") / "development" / "tools.yml.j2"
RENDERED = Path("inventories") / "development" / "tools.rendered.yml"
API_KEY = "toolsLaneTestKeyNotASecret0000000000"
LITELLM_KEY = "toolsLaneLiteLlmMasterKeyNotASecret000000000000000000"


def render(root: Path, load_only: list[str], environment: Mapping[str, str]) -> Path:
    """Write the tools lane host vars and return the rendered file.

    Args:
        root: repository root.
        load_only: every language code the lane's image prefetches models for.
            Pinning the whole set keeps the build ARG constant, so the prefetch
            layer is not rebuilt once per batch.
        environment: the environment the infra runner is started with; its
            cache base and models directory become ``DIR_CACHE`` and
            ``AI_MODELS_STORE_PATH``, so every bind the inventory writes lies
            below the base the runner mounts at its host path.

    Returns:
        The rendered file.

    Raises:
        KeyError: the environment names no cache base or models directory.
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
        autoescape=select_autoescape(default_for_string=False),
    )
    body = env.get_template(template_path.name).render(
        load_only=sorted(load_only),
        s1_api_key=API_KEY,
        litellm_master_key=LITELLM_KEY,
        cache_dir=environment[BASE_KEY],
        models_dir=environment[MODELS_KEY],
    )
    rendered = root / RENDERED
    rendered.write_text(body, encoding="utf-8")
    return rendered
