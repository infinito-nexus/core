from __future__ import annotations

import base64
import json
import re
from html.entities import html5
from urllib.parse import quote, quote_plus

from ._spec_secrets_fakes import RAW, leaks


def xml(text: str) -> str:
    """Escape text the way Playwright's JUnit reporter writes an attribute.

    Args:
        text: the text.

    Returns:
        The text with ``& " ' < >`` as entities.
    """
    for char, entity in (
        ("&", "&amp;"),
        ('"', "&quot;"),
        ("'", "&apos;"),
        ("<", "&lt;"),
        (">", "&gt;"),
    ):
        text = text.replace(char, entity)
    return text


def escaped(text: str, escape) -> str:
    """Escape every character but ASCII letters and digits, as encoders do.

    Args:
        text: the text.
        escape: turns one character into its escape.

    Returns:
        The escaped text.
    """
    return "".join(c if c.isascii() and c.isalnum() else escape(c) for c in text)


def utf16(char: str) -> str:
    """Escape a character as JSON does, a pair of ``\\u`` for one past U+FFFF.

    Args:
        char: the character.

    Returns:
        Its escape.
    """
    units = char.encode("utf-16-be")
    return "".join(f"\\u{units[at : at + 2].hex()}" for at in range(0, len(units), 2))


NAMED = {
    value: f"&{name}"
    for name, value in sorted(html5.items(), reverse=True)
    if name.endswith(";") and len(value) == 1
}


def forms(value: str) -> dict[str, str]:
    """Spell a value in each form it reaches the output in.

    Args:
        value: the value.

    Returns:
        Each form by name.
    """
    raw, plain = value.encode(), json.dumps(value)[1:-1]
    return {
        "raw": value,
        "json": plain,
        "json_unicode": json.dumps(value, ensure_ascii=False)[1:-1],
        "xml": xml(value),
        "json_in_xml_attribute": xml(plain),
        "percent_encoded": quote(value, safe=""),
        "form_encoded": quote_plus(value),
        "double_percent": quote(quote(value, safe=""), safe=""),
        "form_then_percent": quote(quote_plus(value), safe=""),
        "preview_truncated_49": value[:49] + "…",
        "single_quoted_inspect": value.replace("\\", "\\\\").replace("'", "\\'"),
        "json_in_json": json.dumps(plain)[1:-1],
        "base64": base64.b64encode(raw).decode(),
        "base64_urlsafe_unpadded": base64.urlsafe_b64encode(raw).decode().rstrip("="),
        "encode_uri_component": quote(value, safe="-_.!~*'()"),
        "encode_uri": quote(value, safe=";,/?:@&=+$-_.!~*'()#"),
        "url_search_params": quote_plus(value, safe="*-._"),
        "html_decimal": escaped(value, lambda char: f"&#{ord(char)};"),
        "html_hex": escaped(value, lambda char: f"&#x{ord(char):X};"),
        "html_named": escaped(value, lambda char: NAMED.get(char, char)),
        "json_unicode_escapes": escaped(value, utf16),
        "js_code_point_escapes": escaped(value, lambda char: f"\\u{{{ord(char):x}}}"),
        "ascii_repr": ascii(value)[1:-1],
        "ansi_inverse_diff": escaped(value, lambda char: f"\x1b[7m{char}\x1b[27m"),
        "python_bytes_repr": repr(raw)[2:-1],
        "junit_sgr_remnant": escaped(value, lambda char: f"[7m{char}[27m"),
        "node_buffer": raw.hex(" "),
        "hex_unspaced": raw.hex(),
        "css_hex": escaped(value, lambda char: f"\\{ord(char):x} "),
        "yaml_single_quoted": value.replace("'", "''"),
    }


SPECIALS = '"\\&<%+ é'
LITERAL = 'Zq%3Ax&Kp9-Ab1[0m"xyZ9-q\\tw&amp;e-Sentinel-Lit-42'
TRIGGERS = {
    "sgr_literal_as_json": ('Ab1[0m"xyZ9', json.dumps('Ab1[0m"xyZ9')[1:-1]),
    "percent_literal_in_junit_attribute": ("Zq%3Ax&Kp9", xml("Zq%3Ax&Kp9")),
}
SPLIT_TRIGGERS = {
    "nine_bytes_percent_in_junit_attribute": ("Zq%3A&Kp9", xml("Zq%3A&Kp9")),
    "nine_bytes_percent_as_json": ('Zq%3A"Kp9', json.dumps('Zq%3A"Kp9')[1:-1]),
}
ENCODER_TRIGGERS = {
    "nine_bytes_quote_in_a_locator": ("Zq%3A'Kp9", "Zq%3A\\'Kp9"),
    "nine_bytes_quotes_in_a_python_repr": ("Zq%3A'\"Kp", repr("Zq%3A'\"Kp")[1:-1]),
    "nine_bytes_lt_in_html_safe_json": ("Zq%3A<Kp9", "Zq%3A\\u003cKp9"),
    "nine_bytes_dot_in_a_regex": ("Zq%3A.Kp9", "Zq%3A\\.Kp9"),
}
MARK_TRIGGERS = {
    "nine_bytes_one_letter_highlighted": ("Zq%3A&Kp9", "Zq%3A&[7mK[27mp9"),
    "nine_bytes_two_letters_highlighted": (
        "Zq%3A&Kp9",
        "Z[7mq[27m%3A&\x1b[7mK\x1b[27mp9",
    ),
}
SNAPSHOT_TRIGGERS = {
    "nine_bytes_quote_doubled_in_an_aria_snapshot_key": ("ab'cdefgh", "ab''cdefgh"),
}
NORMALIZED_TRIGGERS = {
    "space_run_collapsed_in_an_accessible_name": ("abcd  efgh", "abcd efgh"),
    "invisibles_dropped_from_an_accessible_name": (
        "ab\N{ZERO WIDTH SPACE}cd\N{SOFT HYPHEN}efgh",
        "abcdefgh",
    ),
}
LITERALS = {
    **TRIGGERS,
    **SPLIT_TRIGGERS,
    **ENCODER_TRIGGERS,
    **MARK_TRIGGERS,
    **SNAPSHOT_TRIGGERS,
    **NORMALIZED_TRIGGERS,
    "css_escaped_leading_digit": ("1q%3A&Kp9", "\\31 q\\%3A\\&Kp9"),
    **{
        f"literals_{name}": (LITERAL, encode(LITERAL))
        for name, encode in (
            ("raw", str),
            ("json", lambda text: json.dumps(text)[1:-1]),
            ("xml", xml),
            ("json_in_xml_attribute", lambda text: xml(json.dumps(text)[1:-1])),
            ("percent_encoded", lambda text: quote(text, safe="")),
            ("form_encoded", quote_plus),
        )
    },
}
BASIC_USERS = ("abc", "ab", "a", "user", "admin:x")
SPACED = "a b!c d!e f!g h"
PADDING = b"." * 600
ANSI = re.compile("\x1b\\[[0-9;]*m")


def form_leaks(module, value: str) -> list[str]:
    """Mask each form a value reaches the output in, one line each.

    Args:
        module: the loaded masker.
        value: the value; ``SPECIALS`` holds, in 9 bytes, one character of
            each class an encoder escapes.

    Returns:
        The forms not masked whole, colour codes aside, so that a byte of the
        value shows.
    """
    masks = module.windows([value.encode()])
    found = []
    for name, form in forms(value).items():
        out = module.Stream(masks).feed(f"<<{form}>>\n".encode(), final=True)
        if ANSI.sub("", out.decode()).strip()[2:-2].removesuffix("…") != "***":
            found.append(name)
    return found


def literal_leaks(module) -> list[str]:
    """Mask values that hold ``%HH``, ``[Nm``, ``&name;`` or ``\\t`` themselves.

    Args:
        module: the loaded masker.

    Returns:
        The ``LITERALS`` whose form is not masked whole.
    """
    found = []
    for name, (value, form) in LITERALS.items():
        stream = module.Stream(module.windows([value.encode()]))
        if stream.feed(f"<<{form}>>\n".encode(), final=True) != b"<<***>>\n":
            found.append(name)
    return found


def spaced_leaks(module) -> bool:
    """Mask a short value with spaces as ``encodeURIComponent`` writes it.

    Args:
        module: the loaded masker.

    Returns:
        Whether the query value is not masked whole.
    """
    stream = module.Stream(module.windows([SPACED.encode()]))
    line = f"goto /x?k={quote(SPACED, safe='-_.!~*()')}\n".encode()
    return stream.feed(line, final=True) != b"goto /x?k=***\n"


def basic_leaks(module) -> list[str]:
    """Mask a ``Basic`` header of the value behind users of every length.

    Args:
        module: the loaded masker.

    Returns:
        The users behind which a window of the characters that hold value
        bytes only shows.
    """
    masks = module.windows([RAW])
    found = []
    for user in BASIC_USERS:
        prefix = f"{user}:".encode()
        encoded = base64.b64encode(prefix + RAW).decode()
        core = encoded[4 * -(-len(prefix) // 3) : 4 * ((len(prefix) + len(RAW)) // 3)]
        line = f"Authorization: Basic {encoded}\n".encode()
        if leaks(module.Stream(masks).feed(line, final=True).decode(), core):
            found.append(user)
    return found


def chunked(module, size: int) -> bool:
    """Feed the value behind more filler than the stream holds back, in pieces.

    Args:
        module: the loaded masker.
        size: the piece size; 1 feeds byte by byte.

    Returns:
        Whether the output is the filler with the value as one ``***``.
    """
    stream = module.Stream(module.windows([RAW]))
    data = PADDING + RAW + PADDING
    out = b"".join(
        stream.feed(data[at : at + size]) for at in range(0, len(data), size)
    )
    return out + stream.feed(b"", final=True) == PADDING + b"***" + PADDING
