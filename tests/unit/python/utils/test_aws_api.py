from __future__ import annotations

import hashlib
import io
import unittest
import unittest.mock as mock
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlsplit

from utils import aws_api

DOC_CREDENTIALS = {
    "access_key_id": "AKIDEXAMPLE",
    "secret_access_key": "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY",
}
BOTOCORE_CREDENTIALS = {
    "access_key_id": "AKIAIOSFODNN7EXAMPLE",
    "secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
}
S3 = {"region": "us-east-1", "service": "s3"}
BOTOCORE_VECTORS = (
    (
        "PUT",
        "127.0.0.1:8085",
        "/bucket/probe-deadbeef",
        {},
        b"\x00\x01payload~bytes",
        "3946d221e2b6f49f2e9ea7929dde3ef2226aebc5344152bd6b9f9392331de721",
    ),
    (
        "GET",
        "host.example:8333",
        "/b/k",
        {"a": "1", "B": "2", "c": "x y"},
        b"body",
        "6cf8880d3c0baa47750aa5b0736a2b10459546b2f583643689200c01e067e8ec",
    ),
)
IAM_NS = f"{aws_api.IAM['url']}/doc/{aws_api.IAM_VERSION}/"
IAM_ANSWER = (
    f'<GetUserResponse xmlns="{IAM_NS}">'
    "<GetUserResult><User><UserName>ws-a</UserName></User></GetUserResult>"
    "</GetUserResponse>"
).encode()
IAM_ERROR = (
    f'<ErrorResponse xmlns="{IAM_NS}"><Error>'
    "<Type>Sender</Type><Code>NoSuchEntity</Code><Message>no ws-a</Message>"
    "</Error></ErrorResponse>"
).encode()


def doc_example(**overrides):
    """Args:
        overrides: arguments of ``sign`` that differ from the AWS example.

    Returns:
        The signature of the GET ListUsers example of the AWS SigV4 guide.
    """
    arguments = {
        "query": {"Action": "ListUsers", "Version": "2010-05-08"},
        "headers": {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"},
        "body": b"",
        "api": {"region": "us-east-1", "service": "iam"},
        "credentials": DOC_CREDENTIALS,
        "amz_date": "20150830T123600Z",
        **overrides,
    }
    signed = aws_api.sign("GET", "iam.amazonaws.com", "/", **arguments)
    return signed["Authorization"].rsplit("Signature=", 1)[1]


class Recorder:
    """Args:
    answer: the ``(status, body)`` every call returns.
    """

    def __init__(self, answer):
        self.answer = answer
        self.requests = []

    def __call__(self, method, url, headers, body):
        self.requests.append((method, url, headers, body))
        return self.answer


class TestSign(unittest.TestCase):
    def test_the_signature_matches_the_iam_example_of_the_aws_guide(self):
        self.assertEqual(
            doc_example(),
            "5d672d79c15b13162d9279b0855cfba6789a8edb4c82c400e06b5924a6f2b5d7",
        )

    def test_the_signature_matches_botocore_on_s3_requests(self):
        for method, host, path, query, body, signature in BOTOCORE_VECTORS:
            with self.subTest(path=path):
                signed = aws_api.sign(
                    method,
                    host,
                    path,
                    query=query,
                    headers={"x-amz-content-sha256": hashlib.sha256(body).hexdigest()},
                    body=body,
                    api=S3,
                    credentials=BOTOCORE_CREDENTIALS,
                    amz_date="20130524T000000Z",
                )
                self.assertTrue(signed["Authorization"].endswith(f"={signature}"))

    def test_negative_control_another_body_secret_or_day_breaks_the_signature(self):
        expected = doc_example()
        for overrides in (
            {"body": b"Action=CreateUser"},
            {"credentials": {**DOC_CREDENTIALS, "secret_access_key": "other"}},
            {"amz_date": "20150831T123600Z"},
            {"headers": {}},
        ):
            with self.subTest(overrides=sorted(overrides)):
                self.assertNotEqual(doc_example(**overrides), expected)

    def test_a_space_encodes_as_percent_twenty_and_names_sort_by_byte(self):
        self.assertEqual(
            aws_api.canonical_query({"b": "x y", "B": "+/"}), "B=%2B%2F&b=x%20y"
        )

    def test_the_secret_never_appears_in_the_signed_headers(self):
        signed = aws_api.sign(
            "POST",
            "iam.amazonaws.com",
            "/",
            query={},
            headers={},
            body=b"",
            api={"region": "us-east-1", "service": "iam"},
            credentials=DOC_CREDENTIALS,
            amz_date="20150830T123600Z",
        )
        self.assertNotIn(
            DOC_CREDENTIALS["secret_access_key"], " ".join(signed.values())
        )


class TestCalls(unittest.TestCase):
    def test_iam_posts_a_signed_form_and_drops_the_namespaces(self):
        recorder = Recorder((200, IAM_ANSWER))
        with mock.patch.object(aws_api, "send", recorder):
            root = aws_api.iam(DOC_CREDENTIALS, "GetUser", {"UserName": "ws-a"})
        self.assertEqual(root.findtext("GetUserResult/User/UserName"), "ws-a")
        ((method, url, headers, body),) = recorder.requests
        self.assertEqual((method, url), ("POST", "https://iam.amazonaws.com/"))
        self.assertEqual(headers["Content-Type"], aws_api.FORM)
        self.assertIn(
            "SignedHeaders=content-type;host;x-amz-date,", headers["Authorization"]
        )
        self.assertEqual(
            dict(parse_qsl(body.decode())),
            {"Action": "GetUser", "Version": "2010-05-08", "UserName": "ws-a"},
        )
        self.assertNotIn(DOC_CREDENTIALS["secret_access_key"], f"{url}{body}{headers}")

    def test_route53_sends_the_query_it_signed(self):
        recorder = Recorder((200, b"<Answer/>"))
        query = {"dnsname": "ws.example.org", "maxitems": "100"}
        with mock.patch.object(aws_api, "send", recorder):
            aws_api.route53(DOC_CREDENTIALS, "/2013-04-01/hostedzonesbyname", query)
        ((method, url, headers, body),) = recorder.requests
        parts = urlsplit(url)
        self.assertEqual(
            (method, parts.netloc, body), ("GET", "route53.amazonaws.com", b"")
        )
        self.assertEqual(parts.query, aws_api.canonical_query(query))
        self.assertIn("/us-east-1/route53/aws4_request", headers["Authorization"])

    def test_an_error_answer_raises_its_aws_code(self):
        for answer, code in (
            ((404, IAM_ERROR), "NoSuchEntity"),
            ((502, b"<html>bad gateway"), "HTTP 502"),
            ((200, b"not xml"), "HTTP 200"),
        ):
            with (
                self.subTest(code=code),
                mock.patch.object(aws_api, "send", Recorder(answer)),
                self.assertRaises(aws_api.AwsError) as caught,
            ):
                aws_api.iam(DOC_CREDENTIALS, "GetUser", {"UserName": "ws-a"})
            self.assertEqual(caught.exception.code, code)

    def test_send_returns_the_body_of_an_error_answer(self):
        refusal = HTTPError(
            "https://iam.amazonaws.com/", 404, "Not Found", {}, io.BytesIO(IAM_ERROR)
        )
        with mock.patch.object(aws_api, "open_url", side_effect=refusal):
            status, body = aws_api.send("POST", "https://iam.amazonaws.com/", {}, b"x")
        self.assertEqual((status, body), (404, IAM_ERROR))


if __name__ == "__main__":
    unittest.main()
