import re

from ansible.errors import AnsibleFilterError


def to_one_liner(s):
    """
    Collapse any multi-line string into a single line,
    trim extra whitespace, and remove JavaScript comments.
    Supports removal of both '//' line comments and '/*...*/' block comments,
    but preserves '//' inside string literals and templating expressions.
    """
    if not isinstance(s, str):
        raise AnsibleFilterError("to_one_liner() expects a string")

    no_block_comments = re.sub(r"/\*.*?\*/", "", s, flags=re.DOTALL)

    string_pattern = re.compile(r"'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"")
    literals = []

    def _extract(match):
        idx = len(literals)
        literals.append(match.group(0))
        return f"__STR{idx}__"

    temp = string_pattern.sub(_extract, no_block_comments)

    temp = re.sub(r"//.*$", "", temp, flags=re.MULTILINE)

    for idx, lit in enumerate(literals):
        temp = temp.replace(f"__STR{idx}__", lit)

    return re.sub(r"\s+", " ", temp).strip()


class FilterModule:
    def filters(self):
        return {
            "to_one_liner": to_one_liner,
        }
