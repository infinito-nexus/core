from __future__ import annotations

import json
import urllib.parse
import urllib.request

from atmo_bridge.mapping import EVENT_COLLECTION

HTTP_TIMEOUT_SECONDS = 30

LOGIN = (
    "mutation Login($email: String!, $password: String!) "
    "{ login(email: $email, password: $password) { accessToken } }"
)
LOGGED_PERSON = "query LoggedPerson { loggedPerson { id } }"
EVENT_VARIABLES = (
    "$title: String!, $description: String!, $beginsOn: DateTime!, "
    "$endsOn: DateTime, $status: EventStatus, $visibility: EventVisibility, "
    "$draft: Boolean, $onlineAddress: String, $physicalAddress: AddressInput"
)
EVENT_ARGUMENTS = (
    "title: $title, description: $description, beginsOn: $beginsOn, "
    "endsOn: $endsOn, status: $status, visibility: $visibility, draft: $draft, "
    "onlineAddress: $onlineAddress, physicalAddress: $physicalAddress"
)
CREATE_EVENT = (
    f"mutation CreateEvent($organizerActorId: ID!, {EVENT_VARIABLES}) "
    f"{{ createEvent(organizerActorId: $organizerActorId, {EVENT_ARGUMENTS}) {{ id }} }}"
)
UPDATE_EVENT = (
    f"mutation UpdateEvent($eventId: ID!, {EVENT_VARIABLES}) "
    f"{{ updateEvent(eventId: $eventId, {EVENT_ARGUMENTS}) {{ id }} }}"
)
DELETE_EVENT = (
    "mutation DeleteEvent($eventId: ID!) { deleteEvent(eventId: $eventId) { id } }"
)


class BridgeError(RuntimeError):
    pass


class MissingEventError(BridgeError):
    pass


def _json_request(opener, request) -> dict:
    with opener(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


class Pds:
    def __init__(self, base_url: str, opener=urllib.request.urlopen) -> None:
        self.base_url = base_url.rstrip("/")
        self.opener = opener

    def _get(self, method: str, params: dict) -> dict:
        query = urllib.parse.urlencode(
            {k: v for k, v in params.items() if v is not None}
        )
        request = urllib.request.Request(  # noqa: S310 - load_config admits only http(s) base URLs
            f"{self.base_url}/xrpc/{method}?{query}",
            headers={"Accept": "application/json"},
        )
        return _json_request(self.opener, request)

    def _paginate(self, method: str, params: dict, key: str) -> list:
        items, cursor = [], None
        while True:
            page = self._get(method, {**params, "cursor": cursor})
            items.extend(page.get(key) or [])
            cursor = page.get("cursor")
            if not cursor or not page.get(key):
                return items

    def repos(self) -> list:
        return self._paginate("com.atproto.sync.listRepos", {"limit": 1000}, "repos")

    def events(self, did: str) -> list:
        return self._paginate(
            "com.atproto.repo.listRecords",
            {"repo": did, "collection": EVENT_COLLECTION, "limit": 100},
            "records",
        )


class Mobilizon:
    def __init__(
        self, base_url: str, email: str, password: str, opener=urllib.request.urlopen
    ) -> None:
        self.endpoint = f"{base_url.rstrip('/')}/api"
        self.email = email
        self.password = password
        self.opener = opener
        self.token = None
        self.actor_id = None

    def _call(self, query: str, variables: dict) -> dict:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(  # noqa: S310 - load_config admits only http(s) base URLs
            self.endpoint,
            data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        payload = _json_request(self.opener, request)
        errors = payload.get("errors") or []
        if errors:
            messages = "; ".join(str(error.get("message", error)) for error in errors)
            if "not found" in messages.lower():
                raise MissingEventError(messages)
            raise BridgeError(f"Mobilizon GraphQL error: {messages}")
        return payload["data"]

    def login(self) -> Mobilizon:
        self.token = self._call(
            LOGIN, {"email": self.email, "password": self.password}
        )["login"]["accessToken"]
        self.actor_id = self._call(LOGGED_PERSON, {})["loggedPerson"]["id"]
        return self

    def create(self, payload: dict) -> str:
        data = self._call(CREATE_EVENT, {**payload, "organizerActorId": self.actor_id})
        return str(data["createEvent"]["id"])

    def update(self, event_id: str, payload: dict) -> None:
        self._call(UPDATE_EVENT, {**payload, "eventId": event_id})

    def delete(self, event_id: str) -> None:
        self._call(DELETE_EVENT, {"eventId": event_id})
