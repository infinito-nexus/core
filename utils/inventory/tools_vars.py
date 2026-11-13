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

import os
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

TEMPLATE = Path("inventories") / "development" / "tools.yml.j2"
RENDERED = Path("inventories") / "development" / "tools.rendered.yml"
API_KEY = "toolsLaneTestKeyNotASecret0000000000"
LITELLM_KEY = "toolsLaneLiteLlmMasterKeyNotASecret000000000000000000"
LANE_SERVICE = "tools"


def models_dir() -> str:
    """Return the node-local directory the lane keeps its models in.

    Reads the same value ``compose/tools.override.yml`` mounts into the
    runner, so a bind the inventory writes resolves to the host directory
    rather than to something inside the runner that a rebuild discards.
    """
    from utils.env.handlers.infinito.tools.models import KEY, default

    return (os.environ.get(KEY) or "").strip() or default()


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
        autoescape=select_autoescape(default_for_string=False),
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
