import io
import json
import unittest

from ._fixtures import DID, load

clients = load("clients")


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class RecordingOpener:
    def __init__(self, bodies):
        self.bodies = list(bodies)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        return FakeResponse(json.dumps(self.bodies.pop(0)).encode())


class TestHttpClients(unittest.TestCase):
    def test_pds_paginates_repositories(self):
        opener = RecordingOpener(
            [
                {"repos": [{"did": "did:plc:a", "rev": "1"}], "cursor": "next"},
                {"repos": [{"did": "did:plc:b", "rev": "2"}]},
            ]
        )
        repos = clients.Pds("https://pds.example.org/", opener).repos()
        self.assertEqual([repo["did"] for repo in repos], ["did:plc:a", "did:plc:b"])
        self.assertTrue(
            opener.requests[0].full_url.startswith(
                "https://pds.example.org/xrpc/com.atproto.sync.listRepos?"
            )
        )
        self.assertIn("cursor=next", opener.requests[1].full_url)

    def test_pds_lists_event_records_of_one_repository(self):
        opener = RecordingOpener([{"records": [{"uri": "u", "cid": "c", "value": {}}]}])
        self.assertEqual(
            len(clients.Pds("https://pds.example.org", opener).events(DID)), 1
        )
        url = opener.requests[0].full_url
        self.assertIn("com.atproto.repo.listRecords", url)
        self.assertIn("collection=community.lexicon.calendar.event", url)
        self.assertIn("repo=did%3Aplc%3Aalice", url)

    def test_mobilizon_login_then_create_sends_bearer_and_actor(self):
        opener = RecordingOpener(
            [
                {"data": {"login": {"accessToken": "tok"}}},
                {"data": {"loggedPerson": {"id": "42"}}},
                {"data": {"createEvent": {"id": "77"}}},
            ]
        )
        client = clients.Mobilizon(
            "https://event.example.org/", "admin@example.org", "pw", opener
        ).login()
        self.assertEqual(client.create({"title": "t"}), "77")
        self.assertEqual(opener.requests[0].full_url, "https://event.example.org/api")
        self.assertIsNone(opener.requests[0].get_header("Authorization"))
        create = opener.requests[2]
        self.assertEqual(create.get_header("Authorization"), "Bearer tok")
        body = json.loads(create.data)
        self.assertEqual(body["variables"]["organizerActorId"], "42")
        self.assertIn("createEvent(organizerActorId: $organizerActorId", body["query"])

    def test_mobilizon_errors_raise(self):
        opener = RecordingOpener([{"errors": [{"message": "unauthenticated"}]}])
        with self.assertRaises(clients.BridgeError) as caught:
            clients.Mobilizon("https://event.example.org", "a", "b", opener).delete("1")
        self.assertNotIsInstance(caught.exception, clients.MissingEventError)

    def test_mobilizon_not_found_raises_missing_event(self):
        opener = RecordingOpener([{"errors": [{"message": "Event not found"}]}])
        with self.assertRaises(clients.MissingEventError):
            clients.Mobilizon("https://event.example.org", "a", "b", opener).delete("1")


if __name__ == "__main__":
    unittest.main()
