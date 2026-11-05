from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[5]

__all__ = ["PROJECT_ROOT"]
