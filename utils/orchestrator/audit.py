"""The audit trail's hash chain, the stack-free part.

Every tool call, firewall decision, approval and channel message is written to
an insert-only audit store with a hash chain over the entries: each entry
binds the hash of the one before it, so a later edit or deletion breaks the
chain and is detectable. The deployed store is an insert-only Postgres role;
this models the chain and its verification. There is no update and no delete.
"""

from __future__ import annotations

import hashlib
import json

GENESIS = "0" * 64


def _hash(seq: int, kind: str, payload: dict, prev: str) -> str:
    body = json.dumps(
        {"seq": seq, "kind": kind, "payload": payload, "prev": prev},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


class HashChain:
    """An append-only hash chain of audit entries."""

    def __init__(self) -> None:
        self._entries: list[dict] = []

    def append(self, kind: str, payload: dict) -> dict:
        """Append an entry and return it, binding the previous entry's hash.

        Args:
            kind: the entry kind (tool_call, firewall, approval, channel).
            payload: the entry data, free of secret values.
        """
        seq = len(self._entries)
        prev = self._entries[-1]["hash"] if self._entries else GENESIS
        digest = _hash(seq, kind, payload, prev)
        entry = {
            "seq": seq,
            "kind": kind,
            "payload": payload,
            "prev": prev,
            "hash": digest,
        }
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> list[dict]:
        return list(self._entries)

    @staticmethod
    def verify(entries: list[dict]) -> bool:
        """Return whether ``entries`` form an unbroken chain from the genesis
        hash, with every entry's hash and link intact."""
        prev = GENESIS
        for index, entry in enumerate(entries):
            if entry.get("seq") != index or entry.get("prev") != prev:
                return False
            if _hash(index, entry["kind"], entry["payload"], prev) != entry["hash"]:
                return False
            prev = entry["hash"]
        return True


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    chain = HashChain()
    chain.append(
        "firewall", {"role": "maintainer", "verdict": "deny", "target": "upstream/push"}
    )
    chain.append("tool_call", {"tool": "gh", "args_digest": "abc"})
    chain.append("approval", {"owner": "biber", "match": "git_commit"})
    entries = chain.entries
    _expect(HashChain.verify(entries), "fresh chain does not verify")

    tampered = [dict(e) for e in entries]
    tampered[1] = dict(tampered[1], payload={"tool": "gh", "args_digest": "EVIL"})
    _expect(not HashChain.verify(tampered), "a tampered payload still verified")

    dropped = [entries[0], entries[2]]
    _expect(not HashChain.verify(dropped), "a deleted entry was not detected")

    _expect(
        not hasattr(HashChain, "update") and not hasattr(HashChain, "delete"),
        "chain exposes update or delete",
    )
    print("audit hash-chain self-check ok")


if __name__ == "__main__":
    _demo()
