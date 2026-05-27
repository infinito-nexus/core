from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import argparse

MODE_LINE_RE = re.compile(
    r"""^\s*(?P<key>[A-Z0-9_]+)\s*:\s*(?P<value>.+?)\s*(?:#\s*(?P<cmt>.*))?\s*$"""
)


def _parse_bool_literal(text: str) -> bool | None:
    """Convert simple true/false/yes/no/on/off into boolean."""
    t = text.strip().lower()
    if t in ("true", "yes", "on"):
        return True
    if t in ("false", "no", "off"):
        return False
    return None


def load_modes_from_yaml(modes_yaml_path: str) -> list[dict[str, Any]]:
    """
    Load MODE_* definitions from a YAML-like key/value file.

    Expected lines:
      MODE_FOO: true   # comment
      MODE_BAR: false  # comment
      MODE_BAZ: null   # comment
    """
    if not Path(modes_yaml_path).exists():
        raise FileNotFoundError(f"Modes file not found: {modes_yaml_path}")

    modes: list[dict[str, Any]] = []

    with Path(modes_yaml_path).open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip()
            if not line or line.lstrip().startswith("#"):
                continue

            m = MODE_LINE_RE.match(line)
            if not m:
                continue

            key = m.group("key")
            val = m.group("value").strip()
            cmt = (m.group("cmt") or "").strip()

            if not key.startswith("MODE_"):
                continue

            default_bool = _parse_bool_literal(val)

            modes.append(
                {
                    "name": key,
                    "default": default_bool,  # True/False/None
                    "help": cmt or f"Toggle {key}",
                }
            )

    return modes


def add_dynamic_mode_args(
    parser: argparse.ArgumentParser, modes_meta: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """
    Add command-line args dynamically based on MODE_* metadata.

    Returns a spec mapping MODE_NAME -> info used by build_modes_from_args().
    """
    spec: dict[str, dict[str, Any]] = {}

    for meta in modes_meta:
        name = meta["name"]
        default = meta["default"]
        desc = meta["help"]
        short = name.replace("MODE_", "").lower()

        if default is True:
            # MODE_FOO: true  → --skip-foo disables it
            opt = f"--skip-{short}"
            dest = f"skip_{short}"
            parser.add_argument(opt, action="store_true", dest=dest, help=desc)
            spec[name] = {"dest": dest, "default": True, "kind": "bool_true"}

        elif default is False:
            # MODE_BAR: false → --bar enables it
            opt = f"--{short}"
            dest = short
            parser.add_argument(opt, action="store_true", dest=dest, help=desc)
            spec[name] = {"dest": dest, "default": False, "kind": "bool_false"}

        else:
            # MODE_XYZ: null → --xyz true|false
            opt = f"--{short}"
            dest = short
            parser.add_argument(opt, choices=["true", "false"], dest=dest, help=desc)
            spec[name] = {"dest": dest, "default": None, "kind": "explicit"}

    return spec


def build_modes_from_args(
    spec: dict[str, dict[str, Any]], args_namespace: argparse.Namespace
) -> dict[str, Any]:
    """Resolve CLI arguments into a MODE_* dictionary."""
    modes: dict[str, Any] = {}

    for mode_name, info in spec.items():
        dest = info["dest"]
        kind = info["kind"]
        value = getattr(args_namespace, dest, None)

        if kind == "bool_true":
            # if user passed --skip-foo => disable => False, otherwise True
            modes[mode_name] = not value

        elif kind == "bool_false":
            # if user passed --bar => enable => True, otherwise False
            modes[mode_name] = bool(value)

        elif value is not None:
            modes[mode_name] = value == "true"

    return modes
