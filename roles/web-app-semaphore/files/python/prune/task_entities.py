"""Args: none.

Env:
    BAO_ADDR, BAO_CACERT, BAO_ROLE, SEMAPHORE_JWT: the task token login of
        ``utils.openbao_client.login`` of the core tree under INFINITO_SRC_DIR.
    BAO_JWT_TOKEN_TTLS: a JSON object whose values are the ``token_max_ttl``
        of every task token role, such as ``4h``.
"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import os
import re
import sys

ENTITIES = "identity/entity/id"
DURATION = re.compile(r"([0-9]+)([smhd])")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}
STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}")


class PruneRefusedError(Exception):
    """An OpenBao answer or a setting the prune cannot act on."""


def longest_ttl(ttls):
    """Args:
    ttls: the ``token_max_ttl`` of every task token role, such as ``4h``.

    Returns:
        The longest of them as a timedelta.
    """
    spans = []
    for ttl in ttls:
        match = DURATION.fullmatch(str(ttl))
        if match is None:
            raise PruneRefusedError(f"{ttl!r} is no duration")
        spans.append(
            dt.timedelta(seconds=int(match.group(1)) * UNIT_SECONDS[match.group(2)])
        )
    if not spans:
        raise PruneRefusedError("no task token ttl is set")
    return max(spans)


def created(entity):
    """Args:
    entity: the ``data`` of one entity read.

    Returns:
        Its ``creation_time`` in UTC, to the second.
    """
    match = STAMP.match(str(entity.get("creation_time") or ""))
    if match is None:
        raise PruneRefusedError(f"entity {entity.get('id')} carries no creation time")
    return dt.datetime.strptime(match.group(0), "%Y-%m-%dT%H:%M:%S").replace(
        tzinfo=dt.UTC
    )


def task_entity(entity, accessor):
    """Args:
    entity: the ``data`` of one entity read.
    accessor: the mount accessor of the task token auth mount.

    Returns:
        True only when the entity holds an alias and every alias is on
        ``accessor``.
    """
    aliases = entity.get("aliases") or []
    return bool(aliases) and all(
        alias.get("mount_accessor") == accessor for alias in aliases
    )


def prunable(entity, accessor, max_age, now):
    """Args:
    entity: see ``task_entity``.
    accessor: see ``task_entity``.
    max_age: the longest ``token_max_ttl`` of a task token role.
    now: the current time.

    Returns:
        True only for a ``task_entity`` created more than ``max_age`` before
        ``now``.
    """
    return task_entity(entity, accessor) and now - created(entity) > max_age


def answer(bao, method, path):
    """Args:
    bao: the logged-in ``OpenBaoClient``.
    method: the HTTP method.
    path: the API path below ``/v1/``.

    Returns:
        The ``data`` of a 200 or 204 answer.
    """
    status, body = bao.request(method, path, None)
    if status not in (200, 204):
        raise PruneRefusedError(f"{method} {path} answered HTTP {status}")
    return body.get("data") or {}


def run(bao, max_age, now):
    """Args:
    bao: the ``OpenBaoClient`` logged in to the task token auth mount.
    max_age: see ``prunable``.
    now: see ``prunable``.

    Returns:
        ``own``, the task's own entity id, never deleted; ``deleted``, the id
        of every deleted entity; ``kept``, the id of every other task entity
        mapped to the time it turns prunable.
    """
    own = answer(bao, "GET", "auth/token/lookup-self").get("entity_id")
    if not own:
        raise PruneRefusedError("the task token carries no entity")
    aliases = answer(bao, "GET", f"{ENTITIES}/{own}").get("aliases") or []
    if len(aliases) != 1 or not aliases[0].get("mount_accessor"):
        raise PruneRefusedError(f"the own entity {own} holds {len(aliases)} aliases")
    accessor = aliases[0]["mount_accessor"]
    deleted, kept = [], {}
    for entity_id in answer(bao, "GET", f"{ENTITIES}?list=true").get("keys") or []:
        if entity_id == own:
            continue
        entity = answer(bao, "GET", f"{ENTITIES}/{entity_id}")
        if prunable(entity, accessor, max_age, now):
            answer(bao, "DELETE", f"{ENTITIES}/{entity_id}")
            deleted.append(entity_id)
        elif task_entity(entity, accessor):
            kept[entity_id] = created(entity) + max_age
    return {"own": own, "deleted": deleted, "kept": kept}


def main(argv, env, now):
    """Args:
    argv: the command line after the script name, empty.
    env: the task environment.
    now: the current time.

    Returns:
        The exit code.
    """
    if argv:
        print(
            f"prune task entities: takes no argument, got {argv[0]!r}", file=sys.stderr
        )
        return 2
    sys.path.insert(0, env["INFINITO_SRC_DIR"])
    client = importlib.import_module("utils.openbao_client")
    try:
        max_age = longest_ttl(json.loads(env.get("BAO_JWT_TOKEN_TTLS", "{}")).values())
        pruned = run(client.login(env), max_age, now)
    except (client.OpenBaoError, PruneRefusedError, ValueError) as error:
        print(f"prune task entities refused: {error}", file=sys.stderr)
        return 1
    print(f"prune task entities: at {now.isoformat()}")
    print(f"prune task entities: own {pruned['own']}")
    for entity_id, until in pruned["kept"].items():
        print(f"prune task entities: kept {entity_id} until {until.isoformat()}")
    for entity_id in pruned["deleted"]:
        print(f"prune task entities: deleted {entity_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:], os.environ.copy(), dt.datetime.now(dt.UTC)))
