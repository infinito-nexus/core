from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from crossposter import config
from crossposter.sources import Media, SourceItem

SECRETS = {
    "openpost_token": "op-token",
    "database_dsn": "postgresql://crossposter@db/openpost",
    "mail_password": "mail-secret",
    "routes": {"press-mastodon": "secret"},
}


def route() -> dict:
    return {
        "name": "press-mastodon",
        "source": {
            "platform": "mastodon",
            "base_url": "https://microblog.example",
            "account": "press",
        },
        "filters": {
            "visibility": ["public"],
            "exclude_replies": True,
            "exclude_reblogs": True,
            "tags": [],
            "media": "any",
        },
        "targets": {"accounts": ["x-press"]},
        "mode": "review",
        "attribution": {"default": "{text}\n\n{source_url}", "x": "{text}"},
    }


class ConfigFixture:
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        folder = Path(self.directory.name)
        self.secrets = folder / "crossposter-secrets.json"
        self.write_secrets(SECRETS)
        self.raw = {
            "openpost": {
                "base_url": "http://openpost:8080",
                "host": "publish.example",
                "workspace": "workspace-1",
            },
            "secrets_file": str(self.secrets),
            "mail": {
                "host": "mail.example",
                "port": 587,
                "security": "starttls",
                "user": "crossposter",
                "sender": "crossposter@example.org",
            },
            "heartbeat_file": str(folder / "heartbeat"),
            "poll_interval_seconds": 60,
            "opt_out_tag": "nocrosspost",
            "retry": {"max_attempts": 8, "base_seconds": 30, "cap_seconds": 3600},
            "notify": {"recipients": ["press@example.org"]},
            "routes": [route()],
        }

    def tearDown(self) -> None:
        self.directory.cleanup()

    def write_secrets(self, values: dict) -> None:
        self.secrets.write_text(json.dumps(values))

    def broken(self, mutate) -> str:
        raw = copy.deepcopy(self.raw)
        mutate(raw["routes"][0])
        with self.assertRaises(config.ConfigError) as caught:
            config.parse(raw)
        return str(caught.exception)


class TestParse(ConfigFixture, unittest.TestCase):
    def test_a_complete_route_parses(self) -> None:
        parsed = config.parse(self.raw)
        self.assertEqual(parsed.routes[0].source.token, "secret")
        self.assertEqual(parsed.routes[0].targets.accounts, ("x-press",))
        self.assertEqual(parsed.retry.max_attempts, 8)

    def test_secrets_are_read_from_the_secrets_file(self) -> None:
        parsed = config.parse(self.raw)
        self.assertEqual(parsed.openpost.token, "op-token")
        self.assertEqual(parsed.dsn, "postgresql://crossposter@db/openpost")
        self.assertEqual(parsed.mail.password, "mail-secret")

    def test_mail_is_optional(self) -> None:
        raw = copy.deepcopy(self.raw)
        raw["mail"] = None
        self.assertIsNone(config.parse(raw).mail)

    def test_an_unknown_platform_names_route_and_field(self) -> None:
        message = self.broken(lambda item: item["source"].update(platform="myspace"))
        self.assertIn("press-mastodon", message)
        self.assertIn("source.platform", message)

    def test_a_missing_token_names_route_and_field(self) -> None:
        self.write_secrets({**SECRETS, "routes": {"press-mastodon": ""}})
        message = self.broken(lambda item: None)
        self.assertIn("press-mastodon", message)
        self.assertIn("source.token", message)

    def test_targets_need_accounts_or_a_social_set(self) -> None:
        message = self.broken(lambda item: item.update(targets={}))
        self.assertIn("targets", message)

    def test_a_mode_outside_review_and_auto_is_refused(self) -> None:
        message = self.broken(lambda item: item.update(mode="yolo"))
        self.assertIn("mode", message)

    def test_an_attribution_template_needs_the_text(self) -> None:
        message = self.broken(lambda item: item["attribution"].update(x="{source_url}"))
        self.assertIn("attribution.x", message)

    def test_the_source_must_use_https(self) -> None:
        message = self.broken(
            lambda item: item["source"].update(base_url="http://microblog.example")
        )
        self.assertIn("source.base_url", message)

    def test_an_onion_source_may_use_plain_http(self) -> None:
        raw = copy.deepcopy(self.raw)
        onion = "http://microblog." + "a" * 56 + ".onion"
        raw["routes"][0]["source"]["base_url"] = onion
        self.assertEqual(config.parse(raw).routes[0].source.base_url, onion)

    def test_route_names_are_unique(self) -> None:
        raw = copy.deepcopy(self.raw)
        raw["routes"].append(copy.deepcopy(raw["routes"][0]))
        with self.assertRaises(config.ConfigError):
            config.parse(raw)

    def test_new_routes_default_to_review_mode(self) -> None:
        raw = copy.deepcopy(self.raw)
        del raw["routes"][0]["mode"]
        self.assertEqual(config.parse(raw).routes[0].mode, "review")

    def test_attribution_falls_back_to_the_default_template(self) -> None:
        parsed = config.parse(self.raw).routes[0]
        self.assertEqual(parsed.template("linkedin"), "{text}\n\n{source_url}")
        self.assertEqual(parsed.template("x"), "{text}")


def item(**overrides) -> SourceItem:
    values = {
        "uri": "https://microblog.example/users/press/statuses/1",
        "url": "https://microblog.example/@press/1",
        "platform": "mastodon",
        "text": "Hello #news",
        "visibility": "public",
        "tags": ("news",),
        "media": (),
        "in_reply_to": "",
        "reblog": False,
        "spoiler": "",
        "application": "",
    }
    values.update(overrides)
    return SourceItem(**values)


class TestRouting(ConfigFixture, unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.route = config.parse(self.raw).routes[0]

    def test_a_public_post_is_admitted(self) -> None:
        self.assertIsNone(self.route.refusal(item(), "nocrosspost"))

    def test_the_opt_out_hashtag_is_never_forwarded(self) -> None:
        self.assertEqual(
            self.route.refusal(item(tags=("news", "NoCrossPost")), "nocrosspost"),
            "opt-out",
        )

    def test_other_visibilities_are_refused(self) -> None:
        self.assertEqual(
            self.route.refusal(item(visibility="unlisted"), "nocrosspost"), "visibility"
        )

    def test_replies_and_boosts_are_refused(self) -> None:
        self.assertEqual(
            self.route.refusal(item(in_reply_to="https://x/1"), "nocrosspost"), "reply"
        )
        self.assertEqual(self.route.refusal(item(reblog=True), "nocrosspost"), "reblog")

    def test_posts_published_by_openpost_are_refused(self) -> None:
        self.assertEqual(
            self.route.refusal(item(application="OpenPost"), "nocrosspost"), "loop"
        )

    def test_required_tags_filter(self) -> None:
        raw = copy.deepcopy(self.raw)
        raw["routes"][0]["filters"]["tags"] = ["press"]
        tagged = config.parse(raw).routes[0]
        self.assertEqual(tagged.refusal(item(), "nocrosspost"), "tags")
        self.assertIsNone(tagged.refusal(item(tags=("Press",)), "nocrosspost"))

    def test_hashtags_in_the_text_count_when_the_source_lists_no_tags(self) -> None:
        raw = copy.deepcopy(self.raw)
        raw["routes"][0]["filters"]["tags"] = ["press"]
        tagged = config.parse(raw).routes[0]
        self.assertIsNone(
            tagged.refusal(item(text="Launch day #Press", tags=()), "nocrosspost")
        )
        self.assertEqual(
            tagged.refusal(item(text="Press day", tags=()), "nocrosspost"), "tags"
        )

    def test_the_opt_out_hashtag_in_the_text_is_never_forwarded(self) -> None:
        self.assertEqual(
            self.route.refusal(item(text="Hi #NoCrossPost", tags=()), "nocrosspost"),
            "opt-out",
        )

    def test_media_filters(self) -> None:
        raw = copy.deepcopy(self.raw)
        raw["routes"][0]["filters"]["media"] = "required"
        required = config.parse(raw).routes[0]
        self.assertEqual(required.refusal(item(), "nocrosspost"), "media")
        picture = Media(
            url="https://microblog.example/a.png",
            mime="image/png",
            description="",
            size=1024,
        )
        self.assertIsNone(required.refusal(item(media=(picture,)), "nocrosspost"))
        raw["routes"][0]["filters"]["media"] = "none"
        self.assertEqual(
            config.parse(raw).routes[0].refusal(item(media=(picture,)), "nocrosspost"),
            "media",
        )
