from __future__ import annotations

import unittest

from crossposter import adapt
from crossposter.sources import Media, SourceItem

URL = "https://example.org/a/very/long/path/that/would/count/far/more/than/twenty/three"
PICTURE = Media(
    url="https://microblog.example/a.png",
    mime="image/png",
    description="A red square",
    size=2048,
)
SMALL_VIDEO = Media(
    url="https://video.example/a.mp4",
    mime="video/mp4",
    description="",
    size=10 * 1024 * 1024,
)
LARGE_VIDEO = Media(
    url="https://video.example/b.mp4",
    mime="video/mp4",
    description="",
    size=200 * 1024 * 1024,
)
TEMPLATES = {"default": "{text}\n\n{source_url}", "x": "{text}"}


def item(**overrides) -> SourceItem:
    values = {
        "uri": "https://microblog.example/users/press/statuses/1",
        "url": "https://microblog.example/@press/1",
        "platform": "mastodon",
        "text": "Hello world",
        "visibility": "public",
        "tags": (),
        "media": (),
        "in_reply_to": "",
        "reblog": False,
        "spoiler": "",
        "application": "",
    }
    values.update(overrides)
    return SourceItem(**values)


def prepare(source: SourceItem, network: str, mode: str = "auto") -> adapt.Plan:
    return adapt.prepare(
        source, network, TEMPLATES.get(network, TEMPLATES["default"]), mode
    )


class TestCounting(unittest.TestCase):
    def test_mastodon_counts_a_link_as_twenty_three(self) -> None:
        self.assertEqual(adapt.count(f"see {URL}", "mastodon"), 4 + 23)

    def test_mastodon_counts_a_remote_mention_by_its_username(self) -> None:
        self.assertEqual(
            adapt.count("@alice@social.example hi", "mastodon"), len("@alice hi")
        )

    def test_mastodon_counts_graphemes_not_code_points(self) -> None:
        family = "\U0001f468‍\U0001f469‍\U0001f467"
        self.assertEqual(adapt.count(family, "mastodon"), 1)
        self.assertEqual(adapt.count("é", "mastodon"), 1)

    def test_mastodon_adds_the_content_warning(self) -> None:
        self.assertEqual(adapt.count("body", "mastodon", spoiler="cw"), 6)

    def test_x_weights_cjk_and_emoji_double(self) -> None:
        self.assertEqual(adapt.count("abc", "x"), 3)
        self.assertEqual(adapt.count("日本", "x"), 4)
        self.assertEqual(adapt.count("\U0001f600", "x"), 2)
        self.assertEqual(adapt.count("\U0001f44d\U0001f3fd", "x"), 2)

    def test_x_counts_a_link_as_twenty_three(self) -> None:
        self.assertEqual(adapt.count(URL, "x"), 23)

    def test_fits_respects_the_network_limit(self) -> None:
        self.assertTrue(adapt.fits("a" * 280, "x"))
        self.assertFalse(adapt.fits("a" * 281, "x"))
        self.assertTrue(adapt.fits("a" * 500, "threads"))
        self.assertFalse(adapt.fits("a" * 501, "threads"))


class TestShorten(unittest.TestCase):
    def test_text_within_the_limit_is_unchanged(self) -> None:
        self.assertEqual(adapt.shorten("short", "x"), "short")

    def test_shortening_never_splits_a_word(self) -> None:
        text = " ".join(["word"] * 100)
        shortened = adapt.shorten(text, "x")
        self.assertTrue(adapt.fits(shortened, "x"))
        self.assertTrue(shortened.endswith("…"))
        self.assertTrue(all(token == "word" for token in shortened[:-1].split()))

    def test_shortening_keeps_links_and_hashtags_whole(self) -> None:
        text = ("lorem " * 50) + URL + " #fediverse " + ("ipsum " * 50)
        shortened = adapt.shorten(text, "x")
        self.assertTrue(adapt.fits(shortened, "x"))
        for token in shortened.rstrip("…").split():
            self.assertIn(token, text.split())

    def test_instagram_keeps_at_most_thirty_hashtags(self) -> None:
        text = "caption " + " ".join(f"#tag{index}" for index in range(40))
        shortened = adapt.shorten(text, "instagram")
        self.assertEqual(
            len([token for token in shortened.split() if token.startswith("#")]), 30
        )

    def test_reserve_leaves_room_for_the_attribution(self) -> None:
        shortened = adapt.shorten("a " * 400, "x", reserve=30)
        self.assertLessEqual(adapt.count(shortened, "x"), 250)


class TestHtml(unittest.TestCase):
    def test_mastodon_html_becomes_text_with_links_and_mentions(self) -> None:
        html = (
            '<p>Hello <span class="h-card"><a href="https://social.example/@alice" class="u-url mention">'
            "@<span>alice</span></a></span> see "
            '<a href="https://example.org/page" rel="nofollow"><span class="invisible">https://</span>'
            '<span class="">example.org/page</span></a></p><p>second<br>line '
            '<a href="https://social.example/tags/news" class="mention hashtag">#<span>news</span></a></p>'
        )
        self.assertEqual(
            adapt.html_to_text(html),
            "Hello @alice@social.example see https://example.org/page\n\nsecond\nline #news",
        )


class TestMentions(unittest.TestCase):
    def test_finds_fediverse_handles(self) -> None:
        self.assertEqual(
            adapt.mentions("hi @alice@social.example and @bob@pix.example."),
            ["@alice@social.example", "@bob@pix.example"],
        )

    def test_fediverse_targets_keep_handles(self) -> None:
        self.assertEqual(
            adapt.rewrite_mentions("hi @alice@social.example", "mastodon"),
            "hi @alice@social.example",
        )

    def test_x_gets_plain_names(self) -> None:
        self.assertEqual(
            adapt.rewrite_mentions("hi @alice@social.example", "x"), "hi alice"
        )

    def test_other_commercial_targets_get_profile_links(self) -> None:
        self.assertEqual(
            adapt.rewrite_mentions("hi @alice@social.example", "linkedin"),
            "hi alice (https://social.example/@alice)",
        )


class TestCompose(unittest.TestCase):
    def test_renders_the_template_with_the_source_link(self) -> None:
        self.assertEqual(
            adapt.compose(
                "{text}\n\n{source_url}",
                "hello",
                "https://social.example/@press/1",
                "linkedin",
            ),
            "hello\n\nhttps://social.example/@press/1",
        )

    def test_the_composed_text_fits_the_target(self) -> None:
        composed = adapt.compose(
            "{text}\n\n{source_url}",
            "word " * 200,
            "https://social.example/@press/1",
            "x",
        )
        self.assertTrue(adapt.fits(composed, "x"))
        self.assertTrue(composed.endswith("https://social.example/@press/1"))


class TestPrepare(unittest.TestCase):
    def test_a_text_post_becomes_short_text_with_attribution(self) -> None:
        plan = prepare(item(), "linkedin")
        self.assertEqual(plan.profile, "short_text")
        self.assertEqual(plan.text, "Hello world\n\nhttps://microblog.example/@press/1")
        self.assertFalse(plan.draft_only)
        self.assertEqual(plan.skip, "")

    def test_the_x_template_omits_the_link(self) -> None:
        self.assertEqual(prepare(item(), "x").text, "Hello world")

    def test_review_routes_always_draft(self) -> None:
        self.assertTrue(prepare(item(), "linkedin", mode="review").draft_only)

    def test_a_content_warning_forces_a_draft(self) -> None:
        self.assertTrue(prepare(item(spoiler="politics"), "linkedin").draft_only)

    def test_unmappable_mentions_force_a_draft_on_commercial_targets(self) -> None:
        mentioned = item(text="thanks @alice@social.example")
        self.assertTrue(prepare(mentioned, "linkedin").draft_only)
        self.assertFalse(prepare(mentioned, "mastodon").draft_only)

    def test_images_keep_their_alt_text(self) -> None:
        plan = prepare(item(media=(PICTURE,)), "facebook")
        self.assertEqual(plan.profile, "image_post")
        self.assertEqual(
            [(entry.media.url, entry.alt_text) for entry in plan.media],
            [(PICTURE.url, "A red square")],
        )
        self.assertFalse(plan.media[0].jpeg)

    def test_instagram_images_are_converted_to_jpeg(self) -> None:
        self.assertTrue(prepare(item(media=(PICTURE,)), "instagram").media[0].jpeg)

    def test_pixelfed_skips_posts_without_media(self) -> None:
        self.assertEqual(
            prepare(item(), "pixelfed").skip, "pixelfed accepts only posts with media"
        )
        self.assertEqual(prepare(item(media=(PICTURE,)), "pixelfed").skip, "")

    def test_a_large_video_reaches_mastodon_as_a_link(self) -> None:
        video = item(
            platform="peertube",
            media=(LARGE_VIDEO,),
            title="Talk",
            text="About the talk",
            url="https://video.example/w/abc",
        )
        plan = prepare(video, "mastodon")
        self.assertEqual(plan.media, ())
        self.assertEqual(plan.profile, "short_text")
        self.assertIn("https://video.example/w/abc", plan.text)

    def test_a_small_video_travels_as_a_file(self) -> None:
        video = item(
            platform="peertube",
            media=(SMALL_VIDEO,),
            title="Talk",
            text="About the talk",
            url="https://video.example/w/abc",
        )
        plan = prepare(video, "youtube")
        self.assertEqual(plan.profile, "video")
        self.assertEqual([entry.media for entry in plan.media], [SMALL_VIDEO])
        self.assertEqual(plan.title, "Talk")
        self.assertTrue(plan.text.startswith("Talk\n\nAbout the talk"))
