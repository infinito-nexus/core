"""A tiny boolean filter language over :class:`ComplexityRow` fields.

Grammar (precedence low → high)::

    or_expr   := xor_expr ('or'  xor_expr)*
    xor_expr  := and_expr ('xor' and_expr)*
    and_expr  := not_expr ('and' not_expr)*
    not_expr  := 'not' not_expr | atom
    atom      := '(' or_expr ')' | comparison
    comparison:= FIELD OP value
    OP        := '%%' | '==' | '!=' | '<=' | '>=' | '<' | '>'
    value     := scalar | '{' scalar (',' scalar)* '}'
    scalar    := NUMBER | WORD | QUOTED

``%%`` is "contains" for a scalar string value and "is a member of" for a set
value; ``==`` / ``!=`` against a set mean membership / non-membership. String
comparisons (``==`` ``!=`` ``%%``) are case-insensitive; ``< > <= >=`` are
numeric. A bare expression with no operator (e.g. ``nextcloud``) is shorthand
for ``name %% nextcloud``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

Predicate = Callable[[dict[str, Any]], bool]

_OPERATORS = ("%%", "==", "!=", "<=", ">=", "<", ">")
_KEYWORDS = frozenset({"and", "or", "xor", "not"})
_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<op>%%|==|!=|<=|>=|<|>)
    | (?P<punct>[(){},])
    | (?P<quoted>"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')
    | (?P<word>[A-Za-z0-9_.*-]+)
    """,
    re.VERBOSE,
)


class FilterError(ValueError):
    """A malformed filter expression."""


def _tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    pos = 0
    for match in _TOKEN_RE.finditer(text):
        if match.start() != pos:
            raise FilterError(f"unexpected character at {pos}: {text[pos]!r}")
        pos = match.end()
        kind = match.lastgroup
        value = match.group()
        if kind == "ws":
            continue
        if kind == "quoted":
            value = value[1:-1]
            kind = "word"
        tokens.append((kind, value))
    if pos != len(text):
        raise FilterError(f"unexpected character at {pos}: {text[pos]!r}")
    return tokens


def _coerce_scalar(value: str) -> int | float | str:
    if _NUMBER_RE.match(value):
        return float(value) if "." in value else int(value)
    return value


def _as_number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _apply(actual: Any, op: str, value: Any) -> bool:
    if isinstance(value, frozenset):
        members = {str(v).lower() for v in value}
        present = str(actual).lower() in members
        if op in ("%%", "=="):
            return present
        if op == "!=":
            return not present
        raise FilterError(f"operator {op!r} is not valid against a set")
    if op == "%%":
        return str(value).lower() in str(actual).lower()
    if op in ("==", "!="):
        a_num, v_num = _as_number(actual), _as_number(value)
        if a_num is not None and v_num is not None:
            equal = a_num == v_num
        else:
            equal = str(actual).lower() == str(value).lower()
        return equal if op == "==" else not equal
    a_num, v_num = _as_number(actual), _as_number(value)
    if a_num is None or v_num is None:
        a_num, v_num = str(actual), str(value)
    return {
        "<": a_num < v_num,
        ">": a_num > v_num,
        "<=": a_num <= v_num,
        ">=": a_num >= v_num,
    }[op]


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], fields: frozenset[str]):
        self._tokens = tokens
        self._fields = fields
        self._i = 0

    def parse(self) -> Predicate:
        pred = self._or()
        if self._i != len(self._tokens):
            raise FilterError(f"trailing tokens near {self._peek()!r}")
        return pred

    def _peek(self) -> tuple[str, str] | None:
        return self._tokens[self._i] if self._i < len(self._tokens) else None

    def _is_keyword(self, word: str) -> bool:
        tok = self._peek()
        return tok is not None and tok == ("word", word)

    def _expect_punct(self, char: str) -> None:
        tok = self._peek()
        if tok != ("punct", char):
            raise FilterError(f"expected {char!r}, got {tok!r}")
        self._i += 1

    def _binary(self, keyword: str, lower: Callable[[], Predicate]) -> Predicate:
        left = lower()
        while self._is_keyword(keyword):
            self._i += 1
            right = lower()
            left = self._combine(keyword, left, right)
        return left

    @staticmethod
    def _combine(keyword: str, left: Predicate, right: Predicate) -> Predicate:
        if keyword == "or":
            return lambda f: left(f) or right(f)
        if keyword == "and":
            return lambda f: left(f) and right(f)
        return lambda f: left(f) != right(f)

    def _or(self) -> Predicate:
        return self._binary("or", self._xor)

    def _xor(self) -> Predicate:
        return self._binary("xor", self._and)

    def _and(self) -> Predicate:
        return self._binary("and", self._not)

    def _not(self) -> Predicate:
        if self._is_keyword("not"):
            self._i += 1
            inner = self._not()
            return lambda f: not inner(f)
        return self._atom()

    def _atom(self) -> Predicate:
        if self._peek() == ("punct", "("):
            self._i += 1
            pred = self._or()
            self._expect_punct(")")
            return pred
        return self._comparison()

    def _comparison(self) -> Predicate:
        tok = self._peek()
        if tok is None or tok[0] != "word" or tok[1] in _KEYWORDS:
            raise FilterError(f"expected a field name, got {tok!r}")
        field = tok[1]
        if field not in self._fields:
            raise FilterError(
                f"unknown field {field!r}; known: {', '.join(sorted(self._fields))}"
            )
        self._i += 1
        op_tok = self._peek()
        if op_tok is None or op_tok[0] != "op":
            raise FilterError(f"expected an operator after {field!r}, got {op_tok!r}")
        op = op_tok[1]
        self._i += 1
        value = self._value()
        return lambda f: _apply(f.get(field), op, value)

    def _value(self) -> Any:
        if self._peek() == ("punct", "{"):
            return self._set()
        tok = self._peek()
        if tok is None or tok[0] != "word":
            raise FilterError(f"expected a value, got {tok!r}")
        self._i += 1
        return _coerce_scalar(tok[1])

    def _set(self) -> frozenset[Any]:
        self._expect_punct("{")
        items: list[Any] = []
        while True:
            tok = self._peek()
            if tok is None or tok[0] != "word":
                raise FilterError(f"expected a set member, got {tok!r}")
            self._i += 1
            items.append(_coerce_scalar(tok[1]))
            if self._peek() == ("punct", ","):
                self._i += 1
                continue
            break
        self._expect_punct("}")
        return frozenset(items)


def compile_predicate(expr: str, fields: frozenset[str]) -> Predicate:
    """Compile *expr* into a predicate over a field dict. A bare expression
    with no operator is treated as ``name %% <expr>`` (substring on name)."""
    tokens = _tokenize(expr)
    if not any(kind == "op" for kind, _ in tokens):
        needle = expr.strip().lower()
        return lambda f: needle in str(f.get("name", "")).lower()
    return _Parser(tokens, fields).parse()
