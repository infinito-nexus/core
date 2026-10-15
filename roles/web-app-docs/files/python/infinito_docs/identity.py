"""Resolve the Sphinx identity the documentation is configured with.

``conf.py`` takes project, copyright and author from the environment, which the
role's ``env.j2`` fills from ``services.docs.sphinx``. Callers that run outside
that container - the host side of ``make i18n-extract`` and the unit tests -
read the same configuration through here instead of repeating its values.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_str

SERVICES_FILE = Path("roles") / "web-app-docs" / "meta" / "services.yml"
GENERAL_FILE = Path("group_vars") / "all" / "00_general.yml"


def docs_sphinx_identity(root: Path) -> dict[str, str]:
    """Render ``services.docs.sphinx`` into the environment ``conf.py`` reads.

    Args:
        root: repository root holding the role and the group variables.

    Returns:
        ``{"DOCS_SPHINX_PROJECT": ..., "DOCS_SPHINX_COPYRIGHT": ...,
        "DOCS_SPHINX_AUTHOR": ...}``, with the group variables the configured
        values reference substituted.
    """
    services = load_yaml_str((root / SERVICES_FILE).read_text(encoding="utf-8"))
    general = load_yaml_str((root / GENERAL_FILE).read_text(encoding="utf-8"))
    context = {key: value for key, value in general.items() if isinstance(value, str)}
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(["html", "xml"]),
    )
    return {
        f"DOCS_SPHINX_{key.upper()}": environment.from_string(str(value)).render(
            **context
        )
        for key, value in services["docs"]["sphinx"].items()
    }
