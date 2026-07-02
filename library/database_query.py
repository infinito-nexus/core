#!/usr/bin/python
"""Run a SQL query against a role's database via `container exec`.

Wraps the `container exec -i <container> <client> -v ON_ERROR_STOP=1 ...`
pattern so role tasks don't have to spell out the exec shape by hand.
Works for both shared mode (central `svc-db-*` container) and non-shared
mode (per-role `<entity>-database` container) because the `container`
field of the `database` lookup is already shared-aware. Queries are
piped via stdin, never via the shell, so SQL content doesn't need
shell-escaping.

A new database backend is added by extending `_ENGINES` — the rest of
the module is engine-agnostic.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

from ansible.module_utils.basic import AnsibleModule

DOCUMENTATION = r"""
---
module: database_query
short_description: Run a SQL query against a role-scoped DB via `container exec`.
description:
  - Pipes a SQL payload — either from a file (``query_file``, preferred)
    or a raw string (``query``, opt-in only) — to ``psql`` / ``mariadb``
    (falling back to ``mysql`` on images that still ship only the legacy
    binary) inside the role's DB container via ``container exec``.
  - Substitutes ``%(name)s`` placeholders from ``named_args``
    (psycopg-style) with engine-appropriate escaping before sending
    the SQL to the engine.
  - Works identically in shared mode (central ``svc-db-*``) and non-
    shared mode (per-role ``<entity>-database``) because the
    ``container`` field of the ``database`` lookup is shared-aware.
options:
  config:
    description:
      - The dict returned by C(lookup('database', <consumer_id>)).
        Required keys: C(type), C(container), C(username), C(name),
        C(password). Marked C(no_log) so the password doesn't leak
        through Ansible's verbose mode.
    type: dict
    required: true
  query:
    description:
      - Raw SQL string. Mutually exclusive with C(query_file). Allowed
        only where genuinely needed (e.g. SQL rendered from a Jinja
        template via ``lookup('template', ...)``); the lint test
        ``test_no_raw_database_query_string.py`` requires
        ``# nocheck: database-query-raw`` on the same or immediately
        preceding line.
    type: str
  query_file:
    description:
      - Path (on the Ansible controller) to a file containing SQL.
        Mutually exclusive with C(query). Preferred form — the lint
        test rejects bare C(query) usage without an explicit nocheck
        marker.
    type: path
  named_args:
    description:
      - Mapping of placeholder names to values. Each ``%(name)s`` in
        the SQL is replaced with the engine-escaped form of
        ``named_args[name]``. Supported value types are ``str``,
        ``int``, ``float``, ``bool``, and ``None``; anything else
        must be pre-serialised by the caller (e.g. ``to_json`` for
        jsonb columns).
    type: dict
    default: {}
  expect_rows:
    description:
      - When C(true), the module adds the engine's "tuple-only" flags
        and parses the result into C(rows) — a list of rows, each row
        a list of column-value strings. NULL becomes the empty
        string. Use this for SELECTs whose result a caller needs.
    type: bool
    default: false
returns:
  rc:
    description: Exit code of the engine client invocation.
    type: int
  stdout:
    description: Verbatim stdout (after tuple-only formatting when expect_rows).
    type: str
  stderr:
    description: Verbatim stderr.
    type: str
  rows:
    description: Parsed rows; only present when C(expect_rows) is true.
    type: list
"""

_READ_ONLY_PREFIXES = ("SELECT ", "SHOW ", "EXPLAIN ", "WITH ", "VALUES ")
_REQUIRED_CONFIG_KEYS = ("type", "container", "username", "name", "password")

# Match psycopg-style placeholders: %(identifier)s. The identifier must
# be a valid Python identifier so we don't chew through legitimate
# `%(` byte sequences inside SQL string literals.
_NAMED_ARG_RE = re.compile(r"%\(([A-Za-z_][A-Za-z0-9_]*)\)s")


# Per-engine command-line + escape dialect. Each entry is consumed by
# `_build_cmd()` and `_escape_value()`. Adding a new backend = one
# entry here; the rest of the module is engine-agnostic.
# `binaries`: ordered preferred→fallback; only retried on rc=127 +
# "executable file not found" for the exact binary we tried (handles
# MariaDB ≥11 images that dropped the `mysql` symlink).
_ENGINES: dict[str, dict[str, object]] = {
    "postgres": {
        "binaries": ("psql",),
        "user_flag": "-U",
        "db_flag": "-d",
        "shared_flags": ["-v", "ON_ERROR_STOP=1"],
        "rows_flags": ["-tA"],
        "row_separator": "|",
        "password_env": "PGPASSWORD",
        "string_quote": "'",
        "string_escape_seq": (("'", "''"),),
        "bool_true": "TRUE",
        "bool_false": "FALSE",
    },
    "mariadb": {
        "binaries": ("mariadb", "mysql"),
        "user_flag": "-u",
        "db_flag": "-D",
        "shared_flags": ["--batch"],
        "rows_flags": ["--skip-column-names"],
        "row_separator": "\t",
        "password_env": "MYSQL_PWD",
        "string_quote": "'",
        "string_escape_seq": (("\\", "\\\\"), ("'", "\\'")),
        "bool_true": "1",
        "bool_false": "0",
    },
}


def _build_cmd(
    config: dict,
    *,
    expect_rows: bool,
    binary: str | None = None,
) -> tuple[list[str], dict[str, str]]:
    engine = _ENGINES[config["type"]]
    binaries = engine["binaries"]  # type: ignore[index]
    chosen = binary if binary is not None else binaries[0]  # type: ignore[index]
    cmd: list[str] = [
        "container",
        "exec",
        "-i",
        "-e",
        str(engine["password_env"]),
        config["container"],
        str(chosen),
        str(engine["user_flag"]),
        config["username"],
        str(engine["db_flag"]),
        config["name"],
        *list(engine["shared_flags"]),  # type: ignore[arg-type]
    ]
    if expect_rows:
        cmd.extend(list(engine["rows_flags"]))  # type: ignore[arg-type]
    env_passthrough = {str(engine["password_env"]): str(config["password"])}
    return cmd, env_passthrough


def _resolve_exec_target(config: dict) -> str:
    address = str(config.get("address") or "").strip()
    container = str(config["container"])
    if not address or address == container or not address.startswith('"$('):
        return container
    inner = (
        address[1:-1] if address.startswith('"') and address.endswith('"') else address
    )
    if inner.startswith("$(") and inner.endswith(")"):
        inner = inner[2:-1]
    argv = shlex.split(inner)
    if not argv:
        return container
    proc = subprocess.run(argv, text=True, capture_output=True, check=False)
    return (proc.stdout or "").strip() or container


def _binary_missing(proc: subprocess.CompletedProcess[str], binary: str) -> bool:
    # Match narrowly on the OCI message naming the exact binary we tried —
    # otherwise an engine-side rc=127 would silently mask real failures.
    if proc.returncode != 127:
        return False
    combined = (proc.stdout or "") + (proc.stderr or "")
    return f'"{binary}": executable file not found' in combined


def _escape_value(value: Any, db_type: str) -> str:
    """Return a SQL literal for ``value`` correctly escaped for ``db_type``.

    Supported: ``str``, ``int``, ``float``, ``bool``, ``None``. Anything
    else (lists, dicts, raw bytes) raises ``TypeError`` so callers
    pre-serialise (e.g. ``to_json`` for jsonb columns) explicitly at
    the call site.
    """
    engine = _ENGINES[db_type]
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        # bool is a subclass of int; check before the int branch below.
        return str(engine["bool_true"] if value else engine["bool_false"])
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        escaped = value
        for needle, replacement in engine["string_escape_seq"]:  # type: ignore[attr-defined]
            escaped = escaped.replace(needle, replacement)
        quote = str(engine["string_quote"])
        return f"{quote}{escaped}{quote}"
    raise TypeError(
        f"named_args value of type {type(value).__name__!r} is not supported; "
        f"pre-serialise it (e.g. via `to_json`) before passing."
    )


def _substitute_named_args(sql: str, named_args: dict[str, Any], db_type: str) -> str:
    """Replace every ``%(name)s`` in ``sql`` with the escaped value from
    ``named_args[name]``. Unknown placeholders raise ``KeyError`` so
    typos surface immediately. Unused entries in ``named_args`` are
    silently allowed — callers commonly share a single args dict
    across multiple queries.
    """
    if not _NAMED_ARG_RE.search(sql):
        return sql
    if not named_args:
        first = _NAMED_ARG_RE.search(sql)
        assert first is not None  # noqa: S101 — guarded by the search above
        raise KeyError(
            f"SQL uses placeholder %({first.group(1)})s but named_args is empty"
        )

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in named_args:
            raise KeyError(f"SQL placeholder %({name})s has no entry in named_args")
        return _escape_value(named_args[name], db_type)

    return _NAMED_ARG_RE.sub(_sub, sql)


def _parse_rows(stdout: str, db_type: str) -> list[list[str]]:
    separator = str(_ENGINES[db_type]["row_separator"])
    rows: list[list[str]] = []
    for line in stdout.splitlines():
        if not line:
            continue
        rows.append(line.split(separator))
    return rows


def _is_read_only(sql: str) -> bool:
    stripped = sql.lstrip().upper()
    return any(stripped.startswith(prefix) for prefix in _READ_ONLY_PREFIXES)


def _redact_password_env(cmd: list[str]) -> list[str]:
    password_envs = {str(spec["password_env"]) for spec in _ENGINES.values()}
    out: list[str] = []
    skip_next = False
    for i, arg in enumerate(cmd):
        if skip_next:
            skip_next = False
            continue
        if arg == "-e" and i + 1 < len(cmd) and cmd[i + 1] in password_envs:
            out.append(arg)
            out.append(cmd[i + 1])
            skip_next = True
        elif "=" in arg and arg.split("=", 1)[0] in password_envs:
            out.append(f"{arg.split('=', 1)[0]}=<redacted>")
        else:
            out.append(arg)
    return out


def main() -> None:
    module = AnsibleModule(
        argument_spec={
            "config": {"type": "dict", "required": True},
            "query": {"type": "str"},
            "query_file": {"type": "path"},
            "named_args": {"type": "dict", "default": {}},
            "expect_rows": {"type": "bool", "default": False},
            "mask_values": {"type": "bool", "default": True},
        },
        mutually_exclusive=[("query", "query_file")],
        required_one_of=[("query", "query_file")],
        supports_check_mode=False,
    )

    if module.params["mask_values"]:
        for value in (module.params["config"] or {}).values():
            if isinstance(value, str) and value:
                module.no_log_values.add(value)
        for value in (module.params["named_args"] or {}).values():
            if value is None or isinstance(value, bool):
                continue
            text = str(value)
            if text:
                module.no_log_values.add(text)

    config = module.params["config"]
    missing = [key for key in _REQUIRED_CONFIG_KEYS if not config.get(key)]
    if missing:
        module.fail_json(msg=f"config missing required key(s): {', '.join(missing)}")

    db_type = config["type"]
    if db_type not in _ENGINES:
        module.fail_json(
            msg=f"unsupported database type {db_type!r}; supported: {', '.join(sorted(_ENGINES))}"
        )

    if module.params["query_file"]:
        try:
            with Path(module.params["query_file"]).open(encoding="utf-8") as handle:
                raw_sql = handle.read()
        except OSError as exc:
            module.fail_json(
                msg=f"could not read query_file {module.params['query_file']!r}: {exc}"
            )
    else:
        raw_sql = module.params["query"] or ""

    if not raw_sql.strip():
        module.fail_json(msg="query / query_file resolved to an empty SQL body")

    named_args = module.params.get("named_args") or {}
    try:
        sql = _substitute_named_args(raw_sql, named_args, db_type)
    except (KeyError, TypeError) as exc:
        module.fail_json(msg=f"named_args substitution failed: {exc}")

    expect_rows = bool(module.params["expect_rows"])
    binaries = list(_ENGINES[db_type]["binaries"])  # type: ignore[index]

    exec_config = dict(config)
    exec_config["container"] = _resolve_exec_target(config)

    proc = None
    cmd: list[str] = []
    for index, binary in enumerate(binaries):
        cmd, env_passthrough = _build_cmd(
            exec_config, expect_rows=expect_rows, binary=binary
        )
        env = dict(os.environ)
        env.update(env_passthrough)
        try:
            proc = subprocess.run(
                cmd,
                input=sql,
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
        except OSError as exc:
            module.fail_json(
                msg=f"container exec failed to launch: {exc}",
                cmd=_redact_password_env(cmd),
            )
        if index == len(binaries) - 1 or not _binary_missing(proc, binary):
            break
    assert proc is not None  # noqa: S101 — loop runs at least once (binaries non-empty)

    result = {
        "rc": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "cmd": _redact_password_env(cmd),
        "changed": not _is_read_only(sql),
    }

    if expect_rows:
        result["rows"] = _parse_rows(proc.stdout, db_type)

    if proc.returncode != 0:
        module.fail_json(
            msg=f"{db_type} query failed (rc={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}",
            **result,
        )

    module.exit_json(**result)


if __name__ == "__main__":  # pragma: no cover
    main()
