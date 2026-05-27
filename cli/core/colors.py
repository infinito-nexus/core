from __future__ import annotations


class Style:
    RESET_ALL = "\033[0m"
    BRIGHT = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"


class Fore:
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"


def color_text(text: str, color: str) -> str:
    return f"{color}{text}{Style.RESET_ALL}"
