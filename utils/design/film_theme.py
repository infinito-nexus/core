"""Theme tokens and logo of the corporate design for films and release images.

The tokens follow the motion-presenter theme contract and come from the dark
mode of ``build_palette(design.colors.base)`` and from ``design.font``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.design.branding import DESIGN_ROLE
from utils.design.palette import build_palette
from utils.roles.mapping import ROLE_FILE_META_SERVICES

MODE = "dark"
PALETTE_TOKENS = {
    "--bg": "--design-surface-1",
    "--bg2": "--design-surface-2",
    "--ink": "--design-text",
    "--ink2": "--design-text-muted",
    "--ink3": "--design-border-strong",
    "--accent": "--design-primary",
    "--accent2": "--design-link",
}
MONO_FONT = (
    'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace'
)
THEME_TOKENS = (*PALETTE_TOKENS, "--sans", "--mono")
_PLACEHOLDER = re.compile(r"\{\{(BG2?|INK[23]?|ACCENT2?|SANS|MONO|LOGO)\}\}")


def design_spot(project_root: Path = PROJECT_ROOT) -> dict:
    """Return the ``design`` entry of the design role's services file.

    Args:
        project_root: Repository root holding ``roles/``.
    """
    path = project_root / "roles" / DESIGN_ROLE / ROLE_FILE_META_SERVICES
    return load_yaml_any(str(path))["design"]


def theme(design: dict, project_root: Path = PROJECT_ROOT) -> dict[str, str]:
    """Map the design entry onto the theme tokens and the logo path.

    Args:
        design: The ``design`` entry, as ``design_spot`` returns it.
        project_root: Repository root a relative logo path resolves against.

    Returns:
        ``{"--bg": ..., ..., "--mono": ..., "logo": <absolute path>}``.
    """
    palette = build_palette(design["colors"]["base"])[MODE]
    tokens = {token: palette[source] for token, source in PALETTE_TOKENS.items()}
    tokens["--sans"] = design["font"]["type"]
    tokens["--mono"] = MONO_FONT
    logo = Path(design["logo"])
    tokens["logo"] = str(logo if logo.is_absolute() else project_root / logo)
    return tokens


def render(template: str, tokens: dict[str, str]) -> str:
    """Fill the theme placeholders of an SVG template.

    ``{{BG}}``, ``{{BG2}}``, ``{{INK}}``, ``{{INK2}}``, ``{{INK3}}``,
    ``{{ACCENT}}``, ``{{ACCENT2}}``, ``{{SANS}}`` and ``{{MONO}}`` take the
    token of the same name, ``{{LOGO}}`` the logo as a ``file://`` URL; every
    value is escaped for an XML attribute. Other placeholders stay for the
    content step.

    Args:
        template: The template text.
        tokens: The mapping ``theme`` returns.
    """

    def value(match: re.Match) -> str:
        name = match.group(1)
        raw = (
            Path(tokens["logo"]).as_uri()
            if name == "LOGO"
            else tokens[f"--{name.lower()}"]
        )
        return escape(raw, {'"': "&quot;"})

    return _PLACEHOLDER.sub(value, template)


def main(argv: list[str] | None = None) -> int:
    """Print the theme as JSON, or render a template with it.

    Args:
        argv: ``[]`` prints the tokens; ``["--template", <svg>, "--out",
            <file>]`` writes the rendered template.
    """
    parser = argparse.ArgumentParser(prog="python -m utils.design.film_theme")
    parser.add_argument("--template", help="SVG template with theme placeholders")
    parser.add_argument("--out", help="file the rendered template is written to")
    args = parser.parse_args(argv)
    tokens = theme(design_spot())
    if not args.template:
        print(json.dumps(tokens, indent=2))
        return 0
    if not args.out:
        parser.error("--template needs --out")
    Path(args.out).write_text(
        render(read_text(args.template), tokens), encoding="utf-8"
    )
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
