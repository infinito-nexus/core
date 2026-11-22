from __future__ import annotations

import base64
import html.entities
import json
import re
from functools import partial
from typing import TYPE_CHECKING
from urllib.parse import quote, quote_plus

from spec_secrets import MASK_MIN, normalized

if TYPE_CHECKING:
    from collections.abc import Callable

MASK = b"***"
CHUNK = 1 << 16
HOLD = 64 * MASK_MIN
DEPTH = 2
URLSAFE = bytes.maketrans(b"+/", b"-_")
ESCAPES = (
    rb"(?P<ansi>\x1b\[[0-?]*[ -/]*[@-~])",
    rb"(?P<sgr>\[[0-9;]*m)",
    rb"%(?P<hex>[0-9A-Fa-f]{2})",
    rb"&(?P<entity>#[0-9]{1,7}|#[xX][0-9A-Fa-f]{1,6}|[A-Za-z][A-Za-z0-9]{1,31});?",
    rb"\\u(?P<high>[dD][89abAB][0-9A-Fa-f]{2})\\u(?P<low>[dD][c-fC-F][0-9A-Fa-f]{2})",
    rb"\\u(?P<unit>[0-9A-Fa-f]{4})",
    rb"\\(?:U|u\{)(?P<wide>[0-9A-Fa-f]{1,8})\}?",
    rb"\\x(?P<byte>[0-9A-Fa-f]{2})",
    rb"\\(?P<char>[ -/:-@\[-`{-~bft])",
    rb"\\(?P<css>[0-9A-Fa-f]{1,6}) ?",
    rb"(?P<plus>\+)",
    rb"(?P<quote>'')",
)
ESCAPE = re.compile(b"|".join(ESCAPES))
MARK = re.compile(
    b"|".join(rule for rule in ESCAPES if rule.startswith((b"(?P<ansi>", b"(?P<sgr>")))
)
MODES = ((False, False), (True, False), (False, True))
BACKSLASHED = {b"b": b"\x08", b"f": b"\x0c", b"t": b"\t"}


def code_point(point: int) -> bytes | None:
    """Encode a code point an escape names.

    Args:
        point: the code point.

    Returns:
        Its UTF-8 bytes, or None for a surrogate or a number past Unicode.
    """
    try:
        return chr(point).encode("utf-8")
    except (ValueError, UnicodeEncodeError):
        return None


def unescape(match: re.Match[bytes], plus: bool, octets: bool) -> bytes | None:
    """Decode one match of ``ESCAPE``.

    Args:
        match: the match.
        plus: whether a ``+`` stands for a space, as in a form or a query.
        octets: whether ``\\xHH`` stands for a byte, as in a Python bytes
            repr, instead of a code point.

    Returns:
        The bytes it stands for, empty for a terminal colour code or the
        remnant a JUnit report leaves of one once it drops the ESC, or None
        when it stands for nothing but itself.
    """
    kind = match.lastgroup
    text = match[kind]
    if kind == "plus":
        return b" " if plus else None
    if kind == "quote":
        return b"'"
    if kind in ("ansi", "sgr"):
        return b""
    if kind == "hex" or (kind == "byte" and octets):
        return bytes.fromhex(text.decode())
    if kind == "char":
        return BACKSLASHED.get(text, text)
    if kind == "low":
        high = int(match["high"], 16) - 0xD800
        return code_point(0x10000 + (high << 10) + int(text, 16) - 0xDC00)
    if kind != "entity":
        return code_point(int(text, 16))
    if text.startswith(b"#"):
        hexadecimal = text[1:2] in (b"x", b"X")
        return code_point(
            int(text.lstrip(b"#xX"), 16) if hexadecimal else int(text[1:])
        )
    name = text.decode() + (";" if match[0].endswith(b";") else "")
    found = html.entities.html5.get(name)
    return found.encode("utf-8") if found else None


View = tuple[bytes, list[int], list[int]]


def decode(view: View, plus: bool, octets: bool, pattern: re.Pattern[bytes]) -> View:
    """Decode every escape of a view once.

    Args:
        view: bytes with, per byte, where its source starts and ends.
        plus: whether a ``+`` stands for a space.
        octets: whether ``\\xHH`` stands for a byte.
        pattern: the escapes to decode, ``MARK`` to drop colour codes alone.

    Returns:
        The decoded bytes, each with the source span of its escape.
    """
    data, starts, ends = view
    out, lo, hi, done = bytearray(), [], [], 0
    for match in pattern.finditer(data):
        decoded = unescape(match, plus, octets)
        if decoded is None:
            continue
        start, end = match.span()
        out += data[done:start] + decoded
        lo += starts[done:start] + [starts[start]] * len(decoded)
        hi += ends[done:start] + [ends[end - 1]] * len(decoded)
        done = end
    return bytes(out + data[done:]), lo + starts[done:], hi + ends[done:]


def views(buffer: bytes) -> list[View]:
    """Read output the way each encoder in front of it may have written it.

    Args:
        buffer: the output.

    Returns:
        The output as it is, without its colour codes, which a diff puts
        around any characters, and both decoded up to ``DEPTH`` times, so JSON
        inside an XML attribute counts too, with ``+`` as a space or as itself
        and, where a view holds ``\\x``, with ``\\xHH`` as a byte too: percent,
        HTML and XML entities, JSON, JS, Python, regex and CSS escapes.
    """
    plain = (buffer, list(range(len(buffer))), list(range(1, len(buffer) + 1)))
    found = (
        [plain, decode(plain, False, False, MARK)] if MARK.search(buffer) else [plain]
    )
    layer = found
    for _ in range(DEPTH) if ESCAPE.search(buffer) else ():
        layer = [
            decode(view, plus, octets, ESCAPE)
            for view in layer
            for plus, octets in MODES[: 3 if b"\\x" in view[0] else 2]
        ]
        found = found + layer
    return found


def hex_forms(value: bytes) -> set[bytes]:
    """Spell a value in hex pairs, as a Node ``Buffer`` or a hex dump shows it.

    Args:
        value: the value.

    Returns:
        Lower and upper case, joined and separated by spaces.
    """
    return {
        spelled.encode()
        for text in (value.hex(), value.hex(" "))
        for spelled in (text, text.upper())
    }


def base64_forms(value: bytes) -> set[bytes]:
    """Encode a value in base64 at each byte offset it can start at.

    Args:
        value: the value.

    Returns:
        Standard and URL-safe: the encoding of the value alone, padded and
        unpadded, and per offset of 0, 1 or 2 bytes, as behind the ``user:``
        of a ``Basic`` header, the characters that hold value bytes only.
    """
    found: set[bytes] = set()
    for shift in range(3):
        encoded = base64.b64encode(bytes(shift) + value)
        found.add(encoded[4 * ((shift + 2) // 3) : 4 * ((shift + len(value)) // 3)])
        if not shift:
            found |= {encoded, encoded.rstrip(b"=")}
    return found | {form.translate(URLSAFE) for form in found}


def json_text(text: str, ascii_only: bool) -> str:
    """Escape text as ``JSON.stringify`` writes a string, without the quotes.

    Args:
        text: the text.
        ascii_only: whether every character past ASCII becomes ``\\uXXXX``.

    Returns:
        The escaped text.
    """
    return json.dumps(text, ensure_ascii=ascii_only)[1:-1]


def markup_text(text: str, spell: Callable[[str], str]) -> str:
    """Escape the characters markup reserves, as a report attribute holds them.

    Args:
        text: the text.
        spell: turns one of ``& " ' < >`` into its entity.

    Returns:
        The escaped text.
    """
    return "".join(spell(char) if char in "&\"'<>" else char for char in text)


def escaped(text: str, spell: Callable[[str], str]) -> str:
    """Escape every character but ASCII letters and digits.

    Args:
        text: the text.
        spell: turns one character into its escape.

    Returns:
        The escaped text.
    """
    return "".join(c if c.isascii() and c.isalnum() else spell(c) for c in text)


def utf16(char: str) -> str:
    """Spell a character as JSON ``\\uXXXX`` escapes, a pair past U+FFFF.

    Args:
        char: the character.

    Returns:
        Its escapes.
    """
    units = char.encode("utf-16-be").hex()
    return "".join(f"\\u{units[at : at + 4]}" for at in range(0, len(units), 4))


def css_char(text: str, at: int) -> str:
    """Escape one character as ``CSS.escape`` does.

    Args:
        text: the text.
        at: the character's index.

    Returns:
        A hex escape for a digit that starts the identifier, the character
        itself past ASCII, as a letter, a digit, ``-`` or ``_``, and else the
        character behind a backslash.
    """
    char = text[at]
    if char.isascii() and char.isdigit() and text[:at] in ("", "-"):
        return f"\\{ord(char):x} "
    if not char.isascii() or char.isalnum() or char in "-_":
        return char
    return f"\\{char}"


def quoted_text(text: str) -> str:
    """Quote text as Playwright prints a string in a locator or a call log.

    Args:
        text: the text.

    Returns:
        ``JSON.stringify`` escaping with ``\\"`` back to ``"`` and ``'`` as
        ``\\'``, as between single quotes.
    """
    return json_text(text, ascii_only=False).replace('\\"', '"').replace("'", "\\'")


def sgr_text(text: str) -> str:
    """Mark each run of characters but ASCII letters and digits as a JUnit diff does.

    Args:
        text: the text.

    Returns:
        The text with each such run between ``[7m`` and ``[27m``, the
        remnants of colour codes whose ESC the report dropped.
    """
    return re.sub("[^A-Za-z0-9]+", lambda run: f"[7m{run[0]}[27m", text)


ENTITIES = {"&": "amp", '"': "quot", "'": "apos", "<": "lt", ">": "gt"}
ENCODERS = {
    "sgr": (sgr_text,),
    "hex": (
        partial(quote, safe=""),
        partial(quote, safe="-_.!~*'()"),
        partial(quote, safe=";,/?:@&=+$-_.!~*'()#"),
        lambda text: re.sub("%[0-9A-F]{2}", lambda c: c[0].lower(), quote(text, "")),
    ),
    "plus": (
        partial(quote_plus, safe=""),
        partial(quote_plus, safe="*-._"),
    ),
    "entity": (
        partial(markup_text, spell=lambda char: f"&{ENTITIES[char]};"),
        partial(markup_text, spell=lambda char: f"&#{ord(char)};"),
        partial(markup_text, spell=lambda char: f"&#x{ord(char):X};"),
        partial(markup_text, spell=lambda char: f"&#x{ord(char):x};"),
    ),
    "unit": (
        partial(json_text, ascii_only=True),
        lambda text: json_text(text, ascii_only=False).replace("<", "\\u003c"),
    ),
    "low": (partial(escaped, spell=utf16),),
    "wide": (partial(escaped, spell=lambda char: f"\\u{{{ord(char):x}}}"),),
    "byte": (
        lambda text: ascii(text)[1:-1],
        lambda text: repr(text.encode("utf-8"))[2:-1],
    ),
    "char": (
        partial(json_text, ascii_only=False),
        quoted_text,
        lambda text: repr(text)[1:-1],
        lambda text: re.sub(r"[.*+?^${}()|[\]\\/]", r"\\\g<0>", text),
        lambda text: "".join(css_char(text, at) for at in range(len(text))),
    ),
    "css": (partial(escaped, spell=lambda char: f"\\{ord(char):x} "),),
    "quote": (lambda text: text.replace("'", "''"),),
}
MARKS = {"ansi": ("\x1b[7m", "\x1b[27m"), "sgr": ("[7m", "[27m")}


def encoded_forms(value: bytes) -> set[bytes]:
    """Encode a value the way each of ``ENCODERS`` writes it, once and twice.

    Args:
        value: the value, UTF-8.

    Returns:
        Every encoding, also of each encoding, and the value with each single
        character between the ``MARKS`` of a diff, so a value whose own
        ``%3A``, ``'``, ``[0m`` or ``\\t`` an output decoder turns into fewer
        bytes than a window holds together with an encoder's escapes is still
        found as the encoder wrote it. Each decoder rule of ``ESCAPES`` has
        an entry in ``ENCODERS`` or ``MARKS`` under its group name.
    """
    text = value.decode("utf-8", "replace")
    encoders = {encode for kind in ENCODERS.values() for encode in kind}
    once = {encode(text) for encode in encoders}
    twice = {encode(form) for form in once for encode in encoders}
    marked = {
        f"{text[:at]}{start}{text[at]}{end}{text[at + 1 :]}"
        for start, end in MARKS.values()
        for at in range(len(text))
    }
    return {form.encode("utf-8") for form in once | twice | marked}


def windows(values: list[bytes]) -> frozenset[bytes]:
    """Cut each value's forms and ``encoded_forms`` into windows.

    Args:
        values: the values, each at least ``MASK_MIN`` bytes.

    Returns:
        Every window of ``MASK_MIN`` bytes of the ``views`` of the value and
        of its ``normalized`` form, their ``base64_forms`` and ``hex_forms``,
        and of each of their ``encoded_forms``; output any of whose ``views``
        holds one is masked.
    """
    values = list(dict.fromkeys([*values, *map(normalized, values)]))
    texts = [
        data
        for value in values
        for form in {value} | base64_forms(value) | hex_forms(value)
        for data, _starts, _ends in views(form)
    ]
    texts += [data for value in values for data in encoded_forms(value)]
    return frozenset(
        text[at : at + MASK_MIN]
        for text in texts
        for at in range(len(text) - MASK_MIN + 1)
    )


class Stream:
    """Mask a byte stream, holding back the bytes a window may still start in.

    Args:
        masks: the windows to mask.
    """

    def __init__(self, masks: frozenset[bytes]) -> None:
        self.masks = masks
        self.pending = b""
        self.carry = 0
        self.masked = False

    def feed(self, data: bytes, final: bool = False) -> bytes:
        """Take the next bytes and give back what is safe to pass on.

        Args:
            data: the next bytes.
            final: whether the stream ends with them.

        Returns:
            All bytes but the last ``HOLD`` after the last newline, which no
            window or escape holds, all of them on ``final``, each run of
            windows replaced by one ``MASK``; a run that reaches past them
            goes on masked into the next bytes.
        """
        buffer = self.pending + data
        held = max(len(buffer) - HOLD, buffer.rfind(b"\n") + 1, 0)
        cut = len(buffer) if final else held
        found = sorted(
            (lo[at], hi[at + MASK_MIN - 1])
            for view, lo, hi in views(buffer)
            for at in range(len(view) - MASK_MIN + 1)
            if view[at : at + MASK_MIN] in self.masks
        )
        spans = [[0, self.carry]] if self.carry else []
        for start, end in found:
            if spans and start <= spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], end)
            else:
                spans.append([start, end])
        out, done, carry = bytearray(), 0, 0
        for start, end in spans:
            if start >= cut:
                break
            out += buffer[done:start] + (MASK if start or not self.carry else b"")
            done, carry = min(end, cut), max(end - cut, 0)
            self.masked = True
        self.pending, self.carry = buffer[cut:], carry
        return bytes(out + buffer[done:cut])


def pump(read: Callable, write: Callable, stream: Stream) -> bool:
    """Pass a source through a stream mask until it ends.

    Args:
        read: returns the next bytes, empty at the end.
        write: takes the masked bytes.
        stream: the mask.

    Returns:
        Whether a window was masked.
    """
    while chunk := read():
        write(stream.feed(chunk))
    write(stream.feed(b"", final=True))
    return stream.masked


def relay(source, target, masks: frozenset[bytes]) -> None:
    """Copy a pipe masked, and keep draining it once the target is gone.

    Args:
        source: the child's binary pipe.
        target: this process's binary stream.
        masks: the windows to mask.
    """
    broken = []

    def write(data: bytes) -> None:
        if data and not broken:
            try:
                target.write(data)
                target.flush()
            except OSError as error:
                broken.append(error)

    pump(partial(source.read1, CHUNK), write, Stream(masks))
