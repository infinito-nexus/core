# Dotenv-safe quoting for .env files.
#
# Rules:
# - Always use double quotes
# - Escape backslash and double quote
# - Do NOT do shell-style escaping
#
# Result is safe for:
# - compose --env-file
# - dotenv libraries (PHP, Ruby, Node, Python)
# - passwords containing ', $, spaces, !
#
from __future__ import annotations


class FilterModule:
    def filters(self):
        return {
            "dotenv_quote": self.dotenv_quote,
        }

    @staticmethod
    def dotenv_quote(value):
        if value is None:
            return '""'

        s = str(value)

        # Escape for compose env interpolation:
        # $VAR would be expanded; $$ becomes literal $
        s = s.replace("$", "$$")

        # Escape backslash first, then double quotes
        s = s.replace("\\", "\\\\")
        s = s.replace('"', '\\"')

        return f'"{s}"'
