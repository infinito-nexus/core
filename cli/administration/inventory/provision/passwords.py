from __future__ import annotations

from utils.manager.value_generator import ValueGenerator


def generate_random_password(length: int = 64) -> str:
    return ValueGenerator().generate_strong_password(length)
