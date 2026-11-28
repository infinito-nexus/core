from pathlib import Path

__all__ = ["PROJECT_ROOT"]

PROJECT_ROOT: Path = Path(__file__).resolve().parents[7]
