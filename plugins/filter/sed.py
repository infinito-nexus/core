# sed-safe escaping for replacement strings.
#
# Intended usage:
#   sed "s<d>PATTERN<d>{{ value | sed_escape('<d>') }}<d>"
#
# Escapes:
# - backslash (\)
# - ampersand (&)  → sed replacement reference
# - delimiter (default: |)
#
# Does NOT:
# - add quotes
# - perform shell escaping
#
# Safe for:
# - sed replacement part
# - passwords containing $, ', ", spaces, /, etc.
#
from __future__ import annotations


class FilterModule:
    def filters(self):
        return {
            "sed_escape": self.sed_escape,
        }

    @staticmethod
    def sed_escape(value, delimiter: str = "|") -> str:
        """
        Escape a value for use as the *replacement* part of a sed s/// command.

        Example:
          {{ password | sed_escape('|') }}

        """
        if value is None:
            return ""

        s = str(value)

        # Escape order matters
        s = s.replace("\\", "\\\\")  # backslash
        s = s.replace("&", "\\&")  # sed match reference

        if delimiter:
            s = s.replace(delimiter, "\\" + delimiter)

        return s
