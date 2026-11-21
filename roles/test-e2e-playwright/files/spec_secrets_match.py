from __future__ import annotations

import re
from array import array
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

MASK = b"***"
MASK_MIN = 8
GRAM = MASK_MIN // 2
CHUNK = 1 << 16
ANSI = re.compile(
    rb"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b\n]*(?:\x07|\x1b\\)?|[@-Z\\-_])"
)
XML = re.compile(rb"&(?:(amp|lt|gt|quot|apos)|#([0-9]{1,7})|#[xX]([0-9a-fA-F]{1,6}));")
PERCENT = re.compile(rb"%([0-9a-fA-F]{2})")
FORM = re.compile(rb"%([0-9a-fA-F]{2})|(\+)")
JS = re.compile(
    rb"\\(?:u([dD][89abAB][0-9a-fA-F]{2})\\u([dD][c-fC-F][0-9a-fA-F]{2})"
    rb"|u\{([0-9a-fA-F]{1,6})\}|u([0-9a-fA-F]{4})|x([0-9a-fA-F]{2})"
    rb"|([bfnrtv\"'\\/`]))"
)
NAMED = {b"amp": b"&", b"lt": b"<", b"gt": b">", b"quot": b'"', b"apos": b"'"}
ESCAPED = {b"b": b"\b", b"f": b"\f", b"n": b"\n", b"r": b"\r", b"t": b"\t", b"v": b"\v"}

View = tuple[bytes, array, array]


def code_point(number: int) -> bytes | None:
    try:
        return chr(number).encode("utf-8", "surrogatepass")
    except ValueError:
        return None


def from_xml(found: re.Match[bytes]) -> bytes | None:
    name, decimal, hexadecimal = found.groups()
    if name:
        return NAMED[name]
    return code_point(int(decimal) if decimal else int(hexadecimal, 16))


def from_percent(found: re.Match[bytes]) -> bytes:
    return bytes([int(found.group(1), 16)])


def from_form(found: re.Match[bytes]) -> bytes:
    return b" " if found.group(2) else from_percent(found)


def from_js(found: re.Match[bytes]) -> bytes | None:
    high, low, braced, four, two, char = found.groups()
    if high:
        return code_point(
            0x10000 + ((int(high, 16) - 0xD800) << 10) + int(low, 16) - 0xDC00
        )
    if char:
        return ESCAPED.get(char, char)
    return code_point(int(braced or four or two, 16))


LAYERS = ((XML, from_xml), (PERCENT, from_percent), (FORM, from_form), (JS, from_js))


def decode(view: View, pattern: re.Pattern[bytes], convert: Callable) -> View | None:
    """Decode every token of one encoding, keeping where each byte came from.

    Args:
        view: the bytes, and per byte the start and end of its source span.
        pattern: the tokens of the encoding.
        convert: maps a token to its bytes, or to None to keep it as it is.

    Returns:
        The decoded view, or None when no token was decoded.
    """
    data, starts, ends = view
    out, new_starts, new_ends = bytearray(), array("q"), array("q")
    at = 0
    for found in pattern.finditer(data):
        piece = convert(found)
        if piece is None:
            continue
        first, last = found.span()
        out += data[at:first] + piece
        new_starts += starts[at:first] + array("q", [starts[first]]) * len(piece)
        new_ends += ends[at:first] + array("q", [ends[last - 1]]) * len(piece)
        at = last
    if not at:
        return None
    return bytes(out + data[at:]), new_starts + starts[at:], new_ends + ends[at:]


def strip(view: View) -> View:
    return decode(view, ANSI, lambda _found: b"") or view


def views(data: bytes) -> Iterator[View]:
    """Read a chunk raw and through up to two layers of decoding.

    Args:
        data: a chunk of output or of a file.

    Yields:
        At most 21 views, ANSI escapes removed from each: the raw bytes; each
        of XML entities, percent escapes, form encoding (``+`` as space) and
        JS string escapes; and each of the four again beneath each of them.
    """
    size = len(data)
    raw = strip((data, array("q", range(size)), array("q", range(1, size + 1))))
    yield raw
    for pattern, convert in LAYERS:
        once = decode(raw, pattern, convert)
        if once is None:
            continue
        once = strip(once)
        yield once
        for inner, inner_convert in LAYERS:
            twice = decode(once, inner, inner_convert)
            if twice is not None:
                yield strip(twice)


class Automaton:
    """A suffix automaton over the values: it accepts every piece of one.

    Args:
        values: the values to mask, each at least ``MASK_MIN`` bytes.
    """

    def __init__(self, values: list[bytes]) -> None:
        self.moves: list[dict[int, int]] = [{}]
        self.link = [-1]
        self.depth = [0]
        for value in values:
            last = 0
            for byte in value:
                last = self.extend(last, byte)
        self.longest = max(map(len, values), default=0)
        self.reach = 16 * self.longest + 1024
        self.grams = {
            value[at : at + GRAM]
            for value in values
            for at in range(0, len(value) - GRAM + 1, GRAM)
        }

    def state(self, depth: int, moves: dict[int, int], link: int) -> int:
        self.moves.append(moves)
        self.link.append(link)
        self.depth.append(depth)
        return len(self.depth) - 1

    def extend(self, last: int, byte: int) -> int:
        """Add one byte of a value to the generalized suffix automaton.

        Args:
            last: the state of the value's prefix so far.
            byte: the next byte.

        Returns:
            The state of the longer prefix.
        """
        moves, link, depth = self.moves, self.link, self.depth
        target = moves[last].get(byte)
        if target is not None and depth[target] == depth[last] + 1:
            return target
        current, probe = None, last
        if target is None:
            current = self.state(depth[last] + 1, {}, 0)
            while probe != -1 and byte not in moves[probe]:
                moves[probe][byte] = current
                probe = link[probe]
            if probe == -1:
                return current
            target = moves[probe][byte]
            if depth[target] == depth[probe] + 1:
                link[current] = target
                return current
        clone = self.state(depth[probe] + 1, dict(moves[target]), link[target])
        while probe != -1 and moves[probe].get(byte) == target:
            moves[probe][byte] = clone
            probe = link[probe]
        link[target] = clone
        if current is None:
            return clone
        link[current] = clone
        return current

    def pieces(self, data: bytes) -> Iterator[tuple[int, int]]:
        """Find the runs of a view made of pieces of a value.

        Args:
            data: the bytes of one view.

        Yields:
            Start and exclusive end of each merged run of ``MASK_MIN`` or more
            bytes. One automaton step per byte plus suffix links, which never
            outnumber the steps: linear in ``len(data)``.
        """
        moves, link, depth = self.moves, self.link, self.depth
        state = length = 0
        start = end = -1
        for index, byte in enumerate(data):
            step = moves[state].get(byte)
            while step is None and state:
                state = link[state]
                length = depth[state]
                step = moves[state].get(byte)
            state, length = (0, 0) if step is None else (step, length + 1)
            if length < MASK_MIN:
                continue
            if index + 1 - length > end:
                if end > 0:
                    yield start, end
                start = index + 1 - length
            end = index + 1
        if end > 0:
            yield start, end

    def spans(self, data: bytes) -> list[list[int]]:
        """Find what to mask in a chunk, across all its views.

        Args:
            data: the chunk.

        Returns:
            The source spans to replace, sorted and merged, end exclusive.
        """
        found = []
        for view, starts, ends in views(data) if self.grams else ():
            if any(gram in view for gram in self.grams):
                found += [(starts[a], ends[b - 1]) for a, b in self.pieces(view)]
        merged: list[list[int]] = []
        for start, end in sorted(found):
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
            else:
                merged.append([start, end])
        return merged


class Stream:
    """Mask a byte stream, holding back the tail a value may still run into.

    Args:
        automaton: the values to mask.
    """

    def __init__(self, automaton: Automaton) -> None:
        self.automaton = automaton
        self.pending = b""
        self.masked = False

    def feed(self, data: bytes, final: bool = False) -> bytes:
        """Take the next bytes and give back what is safe to pass on.

        Args:
            data: the next bytes.
            final: whether the stream ends with them.

        Returns:
            The masked bytes up to the last line end, since no value holds
            one; on a line of ``CHUNK`` bytes or more, all but its last
            ``reach`` bytes, which are scanned again with the next bytes;
            everything on ``final``.
        """
        buffer = self.pending + data
        cut = len(buffer) if final else buffer.rfind(b"\n") + 1
        scanned = cut
        if not cut and len(buffer) >= CHUNK + self.automaton.reach:
            scanned, cut = len(buffer), len(buffer) - self.automaton.reach
        spans = self.automaton.spans(buffer[:scanned]) if scanned else []
        for start, end in spans:
            if start < cut < end:
                cut = start
        out, at = bytearray(), 0
        for start, end in spans:
            if end <= cut:
                out += buffer[at:start] + MASK
                at = end
                self.masked = True
        self.pending = buffer[cut:]
        return bytes(out + buffer[at:cut])


def pump(read: Callable, write: Callable, stream: Stream) -> bool:
    """Pass a source through a stream mask until it ends.

    Args:
        read: returns the next bytes, empty at the end.
        write: takes the masked bytes.
        stream: the mask.

    Returns:
        Whether a piece of a value was masked.
    """
    while chunk := read():
        write(stream.feed(chunk))
    write(stream.feed(b"", final=True))
    return stream.masked
