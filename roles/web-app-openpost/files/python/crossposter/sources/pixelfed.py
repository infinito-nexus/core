from __future__ import annotations

from typing import ClassVar

from crossposter.sources.mastodon import MastodonSource


class PixelfedSource(MastodonSource):
    platform = "pixelfed"
    filters: ClassVar[dict[str, str]] = {"exclude_replies": "true"}
