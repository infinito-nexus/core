from __future__ import annotations

from cli.build.docs import markers

DOC = "docs/contributing/design/iam/rbac.md"
BEGIN = "<!-- header-trust-table:begin -->"
END = "<!-- header-trust-table:end -->"
LEGEND = (
    "Rendered by the docs build from the detection in `utils/roles/header_trust.py` "
    "and each role's `sso.header_trust` declaration in `meta/services.yml`."
)


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _code(values: list[str]) -> str:
    return ", ".join(f"`{_cell(value)}`" for value in values)


def _secret(proxy_secret: object) -> str:
    return "no" if proxy_secret is False else f"yes, `{_cell(str(proxy_secret))}`"


def render(
    files: dict[str, list[str]],
    headers: dict[str, list[str]],
    declarations: dict[str, dict],
    exemptions: dict[str, list[tuple[str, str]]],
) -> str:
    """The managed block: one table of header-trust roles, one of exempted files.

    Args:
        files: role -> files that name a trusted header (``header_trust_roles``).
        headers: role -> headers those files name (``header_trust_headers``).
        declarations: role -> its ``sso.header_trust`` declaration.
        exemptions: role -> ``(file, reason)`` per exempted file.

    Raises:
        KeyError: a detected role has no declaration.
    """
    lines = [
        LEGEND,
        "",
        "| Role | Headers it names | Files that name them | Proxy secret | Switched on by |",
        "|---|---|---|---|---|",
    ]
    for role in sorted(files):
        declaration = declarations[role]
        lines.append(
            f"| `{role}` | {_code(headers[role])} | {_code(files[role])} "
            f"| {_secret(declaration['proxy_secret'])} "
            f"| `{_cell(declaration['switch'])}` |"
        )
    if exemptions:
        lines += [
            "",
            "Exempted by `# nocheck: header-trust`, each with the reason its marker states:",
            "",
            "| Role | File | Why it trusts no header |",
            "|---|---|---|",
        ]
        lines.extend(
            f"| `{role}` | `{_cell(rel)}` | {_cell(reason)} |"
            for role in sorted(exemptions)
            for rel, reason in exemptions[role]
        )
    return "\n".join(lines)


def replace_block(text: str, block: str) -> str:
    """*text* with everything between the header-trust markers replaced by *block*.

    Args:
        text: the document.
        block: the rendered block.

    Raises:
        ValueError: the markers are missing, repeated or out of order.
    """
    return markers.replace_block(text, block, begin=BEGIN, end=END, doc=DOC)
