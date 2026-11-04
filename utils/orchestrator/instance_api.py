"""The instance API's registration and lease rules, the stack-free part.

A throwaway instance on a developer machine registers its name together with a
public key. A later registration of the same name with a different key is
refused; the same key takes over, so a restarted instance keeps its name but a
stranger cannot steal it. Provisioned accounts are held on a lease the reaper
deprovisions once it expires. The deployed API persists this; the rules live
here and are unit-tested.
"""

from __future__ import annotations

REGISTERED = "registered"
RENEWED = "renewed"
REFUSED = "refused"


class Registry:
    """Instance-name to public-key registry enforcing the takeover rule."""

    def __init__(self) -> None:
        self._keys: dict[str, str] = {}

    def register(self, name: str, public_key: str) -> str:
        """Register ``name`` under ``public_key``.

        Returns ``registered`` for a new name, ``renewed`` when the same key
        re-registers, and ``refused`` when a different key claims a taken name.
        """
        known = self._keys.get(name)
        if known is None:
            self._keys[name] = public_key
            return REGISTERED
        if known == public_key:
            return RENEWED
        return REFUSED

    def key_of(self, name: str) -> str | None:
        return self._keys.get(name)


def lease_active(granted_at: float, ttl_seconds: float, now: float) -> bool:
    """Return whether a lease granted at ``granted_at`` for ``ttl_seconds`` is
    still active at ``now``. The reaper deprovisions once this is false."""
    return now < granted_at + ttl_seconds


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    reg = Registry()
    _expect(reg.register("dev-laptop", "keyA") == REGISTERED, "new name not registered")
    _expect(reg.register("dev-laptop", "keyA") == RENEWED, "same key not renewed")
    _expect(reg.register("dev-laptop", "keyB") == REFUSED, "name theft allowed")
    _expect(reg.key_of("dev-laptop") == "keyA", "key changed after refusal")
    _expect(reg.register("other", "keyB") == REGISTERED, "distinct name not registered")
    _expect(lease_active(1000.0, 3600.0, 1000.0), "fresh lease not active")
    _expect(lease_active(1000.0, 3600.0, 4599.0), "lease expired early")
    _expect(not lease_active(1000.0, 3600.0, 4600.0), "expired lease still active")
    print("instance-api self-check ok")


if __name__ == "__main__":
    _demo()
