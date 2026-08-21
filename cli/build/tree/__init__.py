from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

from . import __main__ as _main  # noqa: E402

build_mappings = _main.build_mappings
output_graph = _main.output_graph

def find_roles(*args, **kwargs):
    return _main.find_roles(*args, **kwargs)

def process_role(*args, **kwargs):
    _main.build_mappings = build_mappings
    _main.output_graph = output_graph
    return _main.process_role(*args, **kwargs)

def main(*args, **kwargs):
    _main.build_mappings = build_mappings
    _main.output_graph = output_graph
    return _main.main(*args, **kwargs)

def __getattr__(name: str):
    return getattr(_main, name)
