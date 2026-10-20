"""CLI entry point package for the GitHub-hosted runner label update."""

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[4]

__all__ = ["PROJECT_ROOT"]
