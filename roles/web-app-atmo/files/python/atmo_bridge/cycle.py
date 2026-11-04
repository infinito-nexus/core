from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from atmo_bridge.clients import MissingEventError
from atmo_bridge.mapping import UnmappableError, map_event

if TYPE_CHECKING:
    from atmo_bridge.store import Store


@dataclass(frozen=True)
class Action:
    kind: str
    at_uri: str
    cid: str | None = None
    record: dict | None = None
    event_id: str | None = None


def plan(mirrored: dict, records: list) -> list:
    """Decide what Mobilizon must do to match one repository.

    Args:
        mirrored: ``{at_uri: (at_cid, mobilizon_event_id)}`` already mirrored
            for the repository.
        records: ``listRecords`` items of the repository, each with ``uri``,
            ``cid`` and ``value``.

    Returns:
        The create, update and delete actions, deletes last.
    """
    actions = []
    seen = set()
    for item in records:
        uri, cid = item["uri"], item["cid"]
        seen.add(uri)
        current = mirrored.get(uri)
        if current is None:
            actions.append(Action("create", uri, cid, item["value"]))
        elif current[0] != cid:
            actions.append(Action("update", uri, cid, item["value"], current[1]))
    for uri, (_cid, event_id) in sorted(mirrored.items()):
        if uri not in seen:
            actions.append(Action("delete", uri, event_id=event_id))
    return actions


def _apply(
    action: Action, sink, store: Store, appview_url: str, now: float, log
) -> bool:
    if action.kind == "delete":
        try:
            sink.delete(action.event_id)
        except MissingEventError:
            log(f"{action.at_uri}: mirrored event {action.event_id} is already gone")
        store.drop(action.at_uri)
        return True
    try:
        mapped = map_event(action.record, action.at_uri, appview_url)
    except UnmappableError as exc:
        log(f"{action.at_uri}: not mirrored: {exc}")
        return False
    if mapped.unmapped:
        log(
            f"{action.at_uri}: fields without a Mobilizon counterpart: {', '.join(mapped.unmapped)}"
        )
    event_id = None
    if action.kind == "update":
        try:
            sink.update(action.event_id, mapped.payload)
        except MissingEventError:
            log(
                f"{action.at_uri}: mirrored event {action.event_id} is gone, creating it again"
            )
        else:
            event_id = action.event_id
    store.put(action.at_uri, action.cid, event_id or sink.create(mapped.payload), now)
    return True


def run_cycle(
    store: Store, pds, sink_factory, appview_url: str, now: float, log
) -> int:
    """Mirror every changed repository of the PDS once.

    Args:
        store: the mapping store.
        pds: source with ``repos()`` and ``events(did)``.
        sink_factory: callable returning a logged-in Mobilizon client; only
            called when a repository has something to apply.
        appview_url: base URL of the atmo appview.
        now: timestamp recorded on the mapping rows and the heartbeat.
        log: callable taking one message line.

    Returns:
        The number of Mobilizon mutations applied.
    """
    sink = None
    applied = 0
    for repo in pds.repos():
        did, rev = repo["did"], repo["rev"]
        if repo.get("active") is False or store.rev(did) == rev:
            continue
        for action in plan(store.mirrors(did), pds.events(did)):
            sink = sink or sink_factory()
            applied += int(_apply(action, sink, store, appview_url, now, log))
        store.set_rev(did, rev)
    store.beat(now)
    return applied


def healthy(store: Store, now: float, interval_seconds: int) -> bool:
    beat = store.last_beat()
    return beat is not None and now - beat <= 3 * interval_seconds
