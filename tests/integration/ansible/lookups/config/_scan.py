"""Project-wide scanner for `lookup('config', ...)` calls.

Two cached entry points:

* :func:`iter_matches` — returns the deduplicated stream of qualifying
  :class:`LookupMatch` records (regex-parsed, comment-stripped,
  suppression-filtered). Knows nothing about how each test classifies
  the matches.
* :func:`get_context` — returns the :class:`ScanContext` carrying the
  application defaults, user defaults, per-role schemas, and the
  ``application_id``-declaring role set. Built from
  ``utils.cache.{applications,users,yaml}`` so every YAML read goes
  through the process-wide caches.

Per-test classification (literal / variable / wildcard / role-local)
is intentionally NOT done here — each test owns its own builder, so
a change to one classification cannot leak into the others. See the
sibling ``test_*.py`` files.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from utils.annotations.suppress import is_suppressed_at
from utils.cache.applications import get_application_defaults
from utils.cache.files import iter_project_files_with_content
from utils.cache.users import get_user_defaults
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SCHEMA, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

SUPPRESS_RULE: str = "lookup-config-path"


PATTERN = re.compile(
    r"lookup\(\s*['\"]config['\"]\s*,\s*([^,]+?)\s*,\s*['\"]([^'\"]+)['\"]"
)
CONCAT_PATTERN = re.compile(
    r"lookup\(\s*['\"]config['\"]\s*,\s*([^,]+?)\s*,\s*(.+?)\s*\)"
)


def role_id_from_path(file_path: Path) -> str | None:
    """Return the role id when ``file_path`` lives under ``roles/<role>/...``."""
    parts = file_path.parts
    try:
        idx = parts.index("roles")
    except ValueError:
        return None
    if idx + 1 >= len(parts):
        return None
    return parts[idx + 1]


def expr_to_wildcard_path(expr: str) -> str | None:
    """Convert a `~`-concatenated lookup-path expression into a dotted
    path with `*` placeholders for every Jinja variable segment.

    Examples:
      ``'services.' ~ entity_name ~ '.ports.internal.http'`` -> ``services.*.ports.internal.http``
      ``'services.openldap.ports.local.' ~ _ldap_protocol`` -> ``services.openldap.ports.local.*``

    Returns ``None`` when the expression cannot be parsed (mismatched
    quotes, unrecognised operators, etc.) so the caller can skip it.
    """
    parts: list[str] = []
    i = 0
    n = len(expr)
    expecting_value = True
    while i < n:
        ch = expr[i]
        if ch.isspace():
            i += 1
            continue
        if expecting_value:
            if ch in ("'", '"'):
                quote = ch
                j = expr.find(quote, i + 1)
                if j == -1:
                    return None
                parts.append(expr[i + 1 : j])
                i = j + 1
            else:
                j = i
                while j < n and not expr[j].isspace() and expr[j] != "~":
                    j += 1
                token = expr[i:j].strip()
                if not token:
                    return None
                parts.append("*")
                i = j
            expecting_value = False
        elif ch == "~":
            expecting_value = True
            i += 1
        else:
            return None
    if expecting_value:
        return None
    raw = "".join(parts)
    segments = [seg for seg in raw.split(".") if seg != ""]
    return ".".join(segments) if segments else None


@dataclass(frozen=True)
class LookupMatch:
    """One qualifying `lookup('config', <app>, <path>)` occurrence.

    `kind` distinguishes the regex that produced the match:
    * ``"literal"`` — `path_arg` is the FIRST quoted string between the
      app argument and any subsequent comma. May end with ``"."`` for
      partial paths that get a `~ var` suffix elsewhere on the line.
    * ``"concat"`` — `path_arg` is the full expression up to the closing
      paren and is guaranteed to contain at least one ``~``.

    `app_literal` is set iff `app_arg` is a quoted string literal; it
    is the unquoted application id. When `app_literal is None`, the
    application argument is a variable (typically ``application_id``).
    """

    file: Path
    lineno: int
    app_arg: str
    app_literal: str | None
    path_arg: str
    kind: str  # "literal" | "concat"


@dataclass(frozen=True)
class ScanContext:
    """Repo-derived context the four classifications validate against."""

    root: Path
    application_defaults: dict[str, Any]
    user_defaults: dict[str, Any]
    role_schemas: dict[str, dict[str, Any]]
    role_for_app: dict[str, str]
    roles_with_application_id: frozenset[str] = field(default_factory=frozenset)


def _is_quoted(token: str) -> bool:
    return (token.startswith("'") and token.endswith("'")) or (
        token.startswith('"') and token.endswith('"')
    )


def _line_is_commented(text: str, match_start: int) -> bool:
    """Return True when the lookup match sits on a comment-only line or
    is preceded on the same line by a `#` inline comment marker."""
    start = text.rfind("\n", 0, match_start) + 1
    end = text.find("\n", start)
    line = text[start:end] if end != -1 else text[start:]
    if line.lstrip().startswith("#"):
        return True
    idx_call = line.find("lookup")
    idx_hash = line.find("#")
    return 0 <= idx_hash < idx_call


def _has_default_arg(text: str, scan_from: int) -> bool:
    """Return True when the `lookup('config', app, path[, default])` call
    being parsed carries an explicit default value (4th positional arg).

    Mirrors the runtime semantics of `plugins/lookup/config.py`: a third
    `terms` element flips the call to `strict=False`, so a missing path
    silently falls through to the default. Such calls are explicitly
    defensive and out of scope for the path-existence lints — they
    cannot fail at runtime even when the static scan would mark them.

    Starting from ``scan_from`` (the index right after the path literal
    or expression), this skips whitespace and reports whether the next
    significant character inside the same `lookup(...)` call is a
    comma. Bounded at the call's closing paren so we never look past
    it."""
    i = scan_from
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == ",":
            return True
        if ch == ")":
            return False
        return False
    return False


def _build_role_for_app_map(roles_root: Path) -> dict[str, str]:
    """Walk ``roles/`` once and return ``{application_id: role_dir_name}``.

    Replaces the per-app ``plugins.filter.get.role.get_role`` call which
    is O(n) per lookup (it scans every role's vars/main.yml). Calling
    it once per application id makes role-schema preload O(n²); doing
    the walk once here keeps it O(n) and routes every YAML read
    through the process-wide ``utils.cache.yaml.load_yaml_any`` cache.
    """
    mapping: dict[str, str] = {}
    if not roles_root.is_dir():
        return mapping
    for role_dir in roles_root.iterdir():
        if not role_dir.is_dir():
            continue
        vars_file = role_dir / ROLE_FILE_VARS_MAIN
        if not vars_file.is_file():
            continue
        data = load_yaml_any(vars_file, default_if_missing={}) or {}
        if not isinstance(data, dict):
            continue
        app_id = data.get("application_id")
        if isinstance(app_id, str):
            mapping[app_id] = role_dir.name
    return mapping


def _build_role_schemas(
    application_defaults: dict[str, Any],
    role_for_app: dict[str, str],
    roles_root: Path,
) -> dict[str, dict[str, Any]]:
    role_schemas: dict[str, dict[str, Any]] = {}
    for app_id in application_defaults:
        role = role_for_app.get(app_id)
        if role is None:
            continue
        schema_file = roles_root / role / ROLE_FILE_META_SCHEMA
        if not schema_file.is_file():
            continue
        schema = load_yaml_any(schema_file, default_if_missing={}) or {}
        if isinstance(schema, dict):
            role_schemas[app_id] = schema
    return role_schemas


_SCANNED_EXTENSIONS: tuple[str, ...] = (".yml", ".yaml", ".j2")


@functools.lru_cache(maxsize=1)
def get_context() -> ScanContext:
    """Return the cached :class:`ScanContext` for the current repo."""
    root = PROJECT_ROOT
    roles_root = root / "roles"
    application_defaults = get_application_defaults(roles_dir=roles_root)
    user_defaults = get_user_defaults(roles_dir=roles_root)
    role_for_app = _build_role_for_app_map(roles_root)
    role_schemas = _build_role_schemas(application_defaults, role_for_app, roles_root)
    return ScanContext(
        root=root,
        application_defaults=application_defaults,
        user_defaults=user_defaults,
        role_schemas=role_schemas,
        role_for_app=role_for_app,
        roles_with_application_id=frozenset(role_for_app.values()),
    )


def _emit_literal_match(
    text: str, lines: list[str], file_path: Path, m: re.Match[str]
) -> LookupMatch | None:
    if _line_is_commented(text, m.start()):
        return None
    lineno = text.count("\n", 0, m.start()) + 1
    if is_suppressed_at(lines, lineno, SUPPRESS_RULE, mode="same-or-above"):
        return None
    if _has_default_arg(text, m.end()):
        return None
    app_arg = m.group(1).strip()
    path_arg = m.group(2).strip()
    if "{%" in path_arg:
        return None
    app_literal = app_arg.strip("'\"") if _is_quoted(app_arg) else None
    return LookupMatch(
        file=file_path,
        lineno=lineno,
        app_arg=app_arg,
        app_literal=app_literal,
        path_arg=path_arg,
        kind="literal",
    )


def _emit_concat_match(
    text: str, lines: list[str], file_path: Path, m: re.Match[str]
) -> LookupMatch | None:
    if _line_is_commented(text, m.start()):
        return None
    lineno = text.count("\n", 0, m.start()) + 1
    if is_suppressed_at(lines, lineno, SUPPRESS_RULE, mode="same-or-above"):
        return None
    app_arg = m.group(1).strip()
    expr = m.group(2).strip()
    if "~" not in expr or "{%" in expr:
        return None
    app_literal = app_arg.strip("'\"") if _is_quoted(app_arg) else None
    return LookupMatch(
        file=file_path,
        lineno=lineno,
        app_arg=app_arg,
        app_literal=app_literal,
        path_arg=expr,
        kind="concat",
    )


@functools.lru_cache(maxsize=1)
def iter_matches() -> tuple[LookupMatch, ...]:
    """Return the deduplicated tuple of qualifying lookup matches.

    Each project file is read at most once (via the
    ``utils.cache.files`` content cache). The substring pre-filter
    (``"lookup" in text``) and the extension allow-list
    (``_SCANNED_EXTENSIONS``) skip the bulk of files before the regex
    passes ever run.
    """
    matches: list[LookupMatch] = []
    for path_str, text in iter_project_files_with_content(
        extensions=_SCANNED_EXTENSIONS,
        exclude_tests=True,
        exclude_dirs=("docs",),
    ):
        if "lookup" not in text:
            continue
        file_path = Path(path_str)
        lines = text.splitlines()
        for m in PATTERN.finditer(text):
            match = _emit_literal_match(text, lines, file_path, m)
            if match is not None:
                matches.append(match)
        for m in CONCAT_PATTERN.finditer(text):
            match = _emit_concat_match(text, lines, file_path, m)
            if match is not None:
                matches.append(match)
    return tuple(matches)
