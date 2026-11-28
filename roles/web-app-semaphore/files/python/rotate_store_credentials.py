"""Args:
plan <task directory>: prints the extra variables of
    ``playbook-store-credentials.yml`` as JSON: ``gitea_store_token_now``,
    the moment of the run, ``gitea_store_token_expires_at``, two rotation
    periods later, both RFC 3339 with the offset ``+00:00``, and
    ``gitea_store_token_file``, where the playbook leaves the Gitea token it
    minted for the store.
rotate <plan file>: writes that Gitea token to ``platform/data/store/gitea``,
    mints the store's Semaphore token in the Semaphore database, named
    ``store-<expires_at>`` and refused by Semaphore 30 days after the run,
    writes it to ``platform/data/store/semaphore``, and revokes every store
    Semaphore token whose name carries an ``expires_at`` before the run and no
    other. Every entry holds exactly ``token`` and ``expires_at``. Reads
    BAO_ADDR, BAO_CACERT, BAO_TOKEN_FILE (the task's own OpenBao token),
    INFINITO_SRC_DIR, SEMAPHORE_STORE_USERNAME and the SEMAPHORE_DB_HOST,
    SEMAPHORE_DB_PORT, SEMAPHORE_DB, SEMAPHORE_DB_USER and SEMAPHORE_DB_PASS
    of the Semaphore database. No token value reaches an argument or the
    output.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import secrets
import signal
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROTATION_PERIOD = timedelta(days=7)
REVOKE_AFTER = 2 * ROTATION_PERIOD
SEMAPHORE_LIFETIME = timedelta(days=30)
TOKEN_PREFIX = "store-"  # noqa: S105 - the name prefix of the store's tokens, not a credential
TOKEN_BYTES = 22
MIN_TOKEN_CHARS = 40
MOUNT = "platform"
PATHS = {"gitea": "store/gitea", "semaphore": "store/semaphore"}
FIELDS = ("expires_at", "token")
GITEA_FILE = "gitea-token"
RFC3339_NUMERIC_OFFSET = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?[+-]\d{2}:\d{2}"
)


class RotationError(Exception):
    pass


def stamp(moment):
    """Args:
    moment: an aware datetime.

    Returns:
        The moment in UTC to the second, RFC 3339 with the offset ``+00:00``.
    """
    return moment.astimezone(UTC).replace(microsecond=0).isoformat()


def parse(value):
    """Args:
    value: a candidate RFC 3339 time.

    Returns:
        The aware datetime, None for anything without a numeric offset.
    """
    if not isinstance(value, str) or not RFC3339_NUMERIC_OFFSET.fullmatch(value):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def plan(now, workdir):
    """Args:
    now: the moment of the run.
    workdir: the task directory.

    Returns:
        The extra variables of the playbook, see the module docstring.
    """
    return {
        "gitea_store_token_now": stamp(now),
        "gitea_store_token_expires_at": stamp(now + REVOKE_AFTER),
        "gitea_store_token_file": str(Path(workdir) / GITEA_FILE),
    }


def entry(token, expires_at):
    """Args:
    token: the minted token.
    expires_at: the moment the rotation revokes it.

    Returns:
        The OpenBao entry of the token.
    """
    return {"token": token, "expires_at": expires_at}


def entry_findings(candidate):
    """Args:
    candidate: an entry about to be written.

    Returns:
        Every reason the entry is not exactly ``token`` and ``expires_at``
        with an RFC 3339 ``expires_at`` that carries a numeric offset; never
        the token itself.
    """
    findings = []
    if sorted(candidate) != list(FIELDS):
        findings.append(
            f"holds the fields {sorted(candidate)}, expected {list(FIELDS)}"
        )
    if parse(candidate.get("expires_at")) is None:
        findings.append(
            f"expires_at {candidate.get('expires_at')!r} is no RFC 3339 time with a numeric offset"
        )
    token = candidate.get("token")
    if not isinstance(token, str) or len(token) < MIN_TOKEN_CHARS:
        findings.append(f"holds no token of at least {MIN_TOKEN_CHARS} characters")
    return findings


def refuse_entry(kind, candidate):
    """Args:
    kind: ``gitea`` or ``semaphore``.
    candidate: the entry, refused unless :func:`entry_findings` is empty.
    """
    findings = entry_findings(candidate)
    if findings:
        raise RotationError(f"{MOUNT}/data/{PATHS[kind]}: " + "; ".join(findings))


def write_entry(client, kind, candidate):
    """Args:
    client: an ``OpenBaoClient`` holding the task's token.
    kind: ``gitea`` or ``semaphore``.
    candidate: the entry, refused by :func:`refuse_entry` before any write.
    """
    refuse_entry(kind, candidate)
    client.write(MOUNT, PATHS[kind], candidate)


def expired_names(names, now):
    """Args:
    names: the names of the store account's Semaphore tokens.
    now: the moment of the run.

    Returns:
        The names that carry an ``expires_at`` before ``now``; a name of any
        other shape is never listed.
    """
    expired = []
    for name in names:
        if not name or not name.startswith(TOKEN_PREFIX):
            continue
        moment = parse(name[len(TOKEN_PREFIX) :])
        if moment is not None and moment < now:
            expired.append(name)
    return sorted(expired)


def mint_semaphore(connection, username, name, refused_after, token):
    """Args:
    connection: the Semaphore database connection.
    username: the store's account, never an admin.
    name: the token's name.
    refused_after: Semaphore's own ``expires_at`` of the token.
    token: the token value.
    """
    with connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO public.user__token (id, created, expired, user_id, expires_at, name) "
            "SELECT %s, now(), FALSE, account.id, %s, %s "
            'FROM public."user" AS account WHERE account.username = %s AND NOT account.admin '
            "RETURNING user_id",
            (token, refused_after, name, username),
        )
        row = cursor.fetchone()
    if row is None:
        raise RotationError(f"the store account {username} is missing or an admin")


def store_token_names(connection, username):
    """Args:
    connection: the Semaphore database connection.
    username: the store's account.

    Returns:
        The names of the account's tokens, never a token value.
    """
    with connection, connection.cursor() as cursor:
        cursor.execute(
            "SELECT token.name FROM public.user__token AS token "
            'JOIN public."user" AS account ON account.id = token.user_id '
            "WHERE account.username = %s",
            (username,),
        )
        return [row[0] for row in cursor.fetchall()]


def revoke_semaphore(connection, username, names):
    """Args:
    connection: the Semaphore database connection.
    username: the store's account.
    names: the token names to delete.
    """
    if not names:
        return
    with connection, connection.cursor() as cursor:
        cursor.execute(
            'DELETE FROM public.user__token AS token USING public."user" AS account '
            "WHERE account.id = token.user_id AND account.username = %s AND token.name = ANY(%s)",
            (username, list(names)),
        )


def rotate(spec, client, connection, username, new_token=secrets.token_hex):
    """Args:
    spec: the plan :func:`plan` printed.
    client: an ``OpenBaoClient`` holding the task's token.
    connection: the Semaphore database connection.
    username: the store's account.
    new_token: makes a token value from a byte count.

    Returns:
        The lines the run prints, none of them a token.
    """
    now = parse(spec["gitea_store_token_now"])
    expires_at = spec["gitea_store_token_expires_at"]
    if now is None or expires_at != stamp(now + REVOKE_AFTER):
        raise RotationError(
            "the plan holds no run moment with its expires_at 14 days later"
        )
    gitea_file = Path(spec["gitea_store_token_file"])
    if not gitea_file.is_file():
        raise RotationError("the playbook left no Gitea token")
    gitea = gitea_file.read_text(encoding="utf-8").strip()
    gitea_file.unlink()
    write_entry(client, "gitea", entry(gitea, expires_at))
    semaphore = entry(new_token(TOKEN_BYTES), expires_at)
    refuse_entry("semaphore", semaphore)
    mint_semaphore(
        connection,
        username,
        TOKEN_PREFIX + expires_at,
        now + SEMAPHORE_LIFETIME,
        semaphore["token"],
    )
    write_entry(client, "semaphore", semaphore)
    revoked = expired_names(store_token_names(connection, username), now)
    revoke_semaphore(connection, username, revoked)
    refused_after = stamp(now + SEMAPHORE_LIFETIME)
    return [
        f"rotated {MOUNT}/data/{PATHS['gitea']} expires_at={expires_at}",
        f"rotated {MOUNT}/data/{PATHS['semaphore']} expires_at={expires_at} refused_after={refused_after}",
        *(f"revoked semaphore token {name}" for name in revoked),
    ]


def openbao_client(env):
    """Args:
    env: the task environment.

    Returns:
        ``(module, client)``: ``utils.openbao_client`` of INFINITO_SRC_DIR and
        its ``OpenBaoClient`` of BAO_ADDR holding the token in BAO_TOKEN_FILE.
    """
    sys.path.insert(0, env["INFINITO_SRC_DIR"])
    module = importlib.import_module("utils.openbao_client")
    token = Path(env["BAO_TOKEN_FILE"]).read_text(encoding="utf-8").strip()
    return module, module.OpenBaoClient(
        env["BAO_ADDR"], env.get("BAO_CACERT") or None, token
    )


def main(argv, env, clock=lambda: datetime.now(UTC)):
    """Args:
    argv: the command line after the script name.
    env: the task environment.
    clock: answers the moment of the run.

    Returns:
        The exit code.
    """
    if len(argv) != 2 or argv[0] not in ("plan", "rotate"):
        print(
            "rotate_store_credentials.py: expects plan <task directory> or rotate <plan file>",
            file=sys.stderr,
        )
        return 2
    if argv[0] == "plan":
        print(json.dumps(plan(clock(), argv[1]), sort_keys=True))
        return 0
    from semaphore_members import connect

    spec = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    module, client = openbao_client(env)
    connection = connect(env)
    try:
        lines = rotate(spec, client, connection, env["SEMAPHORE_STORE_USERNAME"])
    except (RotationError, module.OpenBaoError) as error:
        print(f"rotate_store_credentials.py: {error}", file=sys.stderr)
        return 1
    finally:
        connection.close()
    for line in lines:
        print(line)
    return 0


def _terminate(signum, _frame):
    raise SystemExit(128 + signum)


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _terminate)
    raise SystemExit(main(sys.argv[1:], dict(os.environ)))
