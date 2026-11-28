from __future__ import annotations

import importlib
import io
import json
import smtplib
import sys
import unittest
import unittest.mock as mock
import urllib.error

from . import PROJECT_ROOT

_TOOLING = str(PROJECT_ROOT / "roles" / "web-svc-access-request" / "files" / "python")
if _TOOLING not in sys.path:
    sys.path.insert(0, _TOOLING)

delivery = importlib.import_module("access_request.delivery")


def _mail(**overrides):
    values = {
        "host": "mail.example.org",
        "port": 587,
        "tls": False,
        "start_tls": True,
        "auth": True,
        "username": "access-request",
        "password": "secret",
        "sender": "access-request@example.org",
        "ca_file": "",
    }
    values.update(overrides)
    return delivery.Mail(**values)


def _zammad(**overrides):
    values = {
        "url": "https://zammad.example.org/",
        "token": "token",
        "group": "Users",
        "ca_file": "",
    }
    values.update(overrides)
    return delivery.Zammad(**values)


class TestMail(unittest.TestCase):
    def test_no_recipient_sends_nothing(self):
        with mock.patch.object(delivery.smtplib, "SMTP") as smtp:
            _mail().send(["", ""], "subject", "body")

        smtp.assert_not_called()

    def test_starttls_logs_in_and_sends_one_message(self):
        with mock.patch.object(delivery.smtplib, "SMTP") as smtp:
            _mail().send(["a@example.org", "b@example.org"], "subject", "body")

        smtp.assert_called_once_with("mail.example.org", 587, timeout=30)
        client = smtp.return_value
        client.starttls.assert_called_once()
        client.login.assert_called_once_with("access-request", "secret")
        message = client.send_message.call_args.args[0]
        self.assertEqual("a@example.org, b@example.org", message["To"])
        self.assertEqual("access-request@example.org", message["From"])
        self.assertEqual("subject", message["Subject"])

    def test_implicit_tls_skips_starttls_and_login_without_auth(self):
        with mock.patch.object(delivery.smtplib, "SMTP_SSL") as smtp_ssl:
            _mail(tls=True, auth=False, port=465).send(["a@example.org"], "s", "b")

        client = smtp_ssl.return_value
        client.starttls.assert_not_called()
        client.login.assert_not_called()
        client.send_message.assert_called_once()

    def test_a_relay_failure_raises_a_delivery_error(self):
        with (
            mock.patch.object(
                delivery.smtplib, "SMTP", side_effect=smtplib.SMTPException("refused")
            ),
            self.assertRaises(delivery.DeliveryError),
        ):
            _mail().send(["a@example.org"], "subject", "body")


class TestZammad(unittest.TestCase):
    def test_a_url_and_a_token_enable_tickets(self):
        self.assertTrue(_zammad().enabled)
        self.assertFalse(_zammad(url="").enabled)
        self.assertFalse(_zammad(token="").enabled)

    def test_a_ticket_is_filed_for_the_requester_in_the_group(self):
        answer = mock.MagicMock()
        answer.__enter__.return_value = io.BytesIO(b'{"id": 7}')
        with mock.patch.object(
            delivery.urllib.request, "urlopen", return_value=answer
        ) as urlopen:
            result = _zammad().ticket("biber@example.org", "title", "body")

        self.assertEqual({"id": 7}, result)
        request = urlopen.call_args.args[0]
        self.assertEqual("https://zammad.example.org/api/v1/tickets", request.full_url)
        self.assertEqual("Token token=token", request.get_header("Authorization"))
        payload = json.loads(request.data)
        self.assertEqual("Users", payload["group"])
        self.assertEqual("guess:biber@example.org", payload["customer_id"])
        self.assertEqual("body", payload["article"]["body"])

    def test_an_unreachable_zammad_raises_a_delivery_error(self):
        with (
            mock.patch.object(
                delivery.urllib.request,
                "urlopen",
                side_effect=urllib.error.URLError("down"),
            ),
            self.assertRaises(delivery.DeliveryError),
        ):
            _zammad().ticket("biber@example.org", "title", "body")


class TestRequestText(unittest.TestCase):
    def test_the_text_names_requester_roles_reason_and_links(self):
        labels = {
            "review_requester": "Requester",
            "form_application": "Application",
            "form_roles": "Roles",
            "form_reason": "Reason",
            "review_title": "Review",
            "review_console": "Console",
        }
        text = delivery.request_text(
            requester="biber",
            email="biber@example.org",
            application="web-app-blog",
            roles=[
                {
                    "id": "editor",
                    "path": "/roles/web-app-blog/editor",
                    "description": "Writes",
                }
            ],
            reason="I write",
            review_url="https://access.example.org/review/1",
            console_url="https://sso.example.org/console",
            labels=labels,
        )

        self.assertEqual(
            [
                "Requester: biber <biber@example.org>",
                "Application: web-app-blog",
                "Roles:",
                "  - editor (/roles/web-app-blog/editor): Writes",
                "Reason:",
                "I write",
                "",
                "Review: https://access.example.org/review/1",
                "Console: https://sso.example.org/console",
            ],
            text.splitlines(),
        )


if __name__ == "__main__":
    unittest.main()
