from __future__ import annotations

import base64
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Mapping

BLOBSTORE = "default"


@dataclass(frozen=True)
class Asset:
    id: str
    size: int
    used_at: float


class NexusStore(Protocol):
    def used(self) -> int: ...

    def assets(self) -> list[Asset]: ...

    def delete(self, asset_id: str) -> None: ...

    def run(self, task_type: str) -> None: ...


def _timestamp(value: object) -> float:
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


class NexusRest:
    def __init__(
        self,
        base: str,
        user: str,
        password: str,
        poll_seconds: float,
        timeout_seconds: float,
    ) -> None:
        """
        Args:
            base: the REST root, as in ``http://127.0.0.1:8081/service/rest``.
            user: the admin user.
            password: its password.
            poll_seconds: the pause between two task state reads.
            timeout_seconds: how long one task may run before the eviction gives up.
        """
        self.base = base.rstrip("/")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds

    def _call(self, method: str, path: str, query: Mapping[str, str]) -> object:
        url = f"{self.base}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, method=method, headers=self.headers)  # noqa: S310 - base is the http:// REST root nexus_from_env builds from .env
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - base is the http:// REST root nexus_from_env builds from .env
            body = response.read()
        return json.loads(body) if body else None

    def reachable(self) -> bool:
        try:
            self._call("GET", "/v1/status", {})
        except (OSError, ValueError):
            return False
        return True

    def used(self) -> int:
        for store in self._call("GET", "/v1/blobstores", {}) or []:
            if store.get("name") == BLOBSTORE:
                return int(store.get("totalSizeInBytes") or 0)
        raise LookupError(f"Nexus has no blob store named {BLOBSTORE}")

    def _pages(self, path: str, query: Mapping[str, str]) -> list[dict]:
        items: list[dict] = []
        token = ""
        while True:
            page = self._call(
                "GET", path, {**query, "continuationToken": token} if token else query
            )
            items.extend(page.get("items") or [])
            token = page.get("continuationToken") or ""
            if not token:
                return items

    def assets(self) -> list[Asset]:
        found: list[Asset] = []
        for repository in self._call("GET", "/v1/repositories", {}) or []:
            if repository.get("type") != "proxy":
                continue
            found.extend(
                Asset(
                    id=item["id"],
                    size=int(item.get("fileSize") or 0),
                    used_at=_timestamp(item.get("lastDownloaded"))
                    or _timestamp(item.get("blobCreated")),
                )
                for item in self._pages(
                    "/v1/assets", {"repository": repository["name"]}
                )
            )
        return found

    def delete(self, asset_id: str) -> None:
        self._call("DELETE", f"/v1/assets/{urllib.parse.quote(asset_id, safe='')}", {})

    def run(self, task_type: str) -> None:
        tasks = self._pages("/v1/tasks", {"type": task_type})
        if not tasks:
            raise LookupError(
                f"Nexus has no {task_type} task; run the package cache bootstrap"
            )
        for task in tasks:
            previous = task.get("lastRun")
            self._call("POST", f"/v1/tasks/{task['id']}/run", {})
            deadline = time.monotonic() + self.timeout_seconds
            while True:
                state = self._call("GET", f"/v1/tasks/{task['id']}", {}) or {}
                if (
                    state.get("currentState") == "WAITING"
                    and state.get("lastRun") != previous
                ):
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"Nexus task {task_type} did not finish in {self.timeout_seconds}s"
                    )
                time.sleep(self.poll_seconds)


def nexus_from_env(
    env: Mapping[str, str], poll_seconds: float, timeout_seconds: float
) -> NexusRest | None:
    """Args:
        env: the variables of `.env`.
        poll_seconds: the pause between two task state reads.
        timeout_seconds: how long one task may run.

    Returns:
        A client of the dev stack's Nexus, or None when it does not answer.
    """
    host = env.get("INFINITO_CACHE_PACKAGE_REST_HOST")
    port = env.get("INFINITO_CACHE_PACKAGE_PORT")
    password = env.get("INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD")
    if not all(value and value.strip() for value in (host, port, password)):
        return None
    client = NexusRest(
        f"http://{host.strip()}:{port.strip()}/service/rest",
        "admin",
        password.strip(),
        poll_seconds,
        timeout_seconds,
    )
    return client if client.reachable() else None
