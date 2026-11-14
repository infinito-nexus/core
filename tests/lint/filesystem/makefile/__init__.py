import re

from tests.lint.filesystem import PROJECT_ROOT

TARGET_RE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_-]*)\s*:(?!:*=)")

__all__ = ["PROJECT_ROOT", "TARGET_RE"]
