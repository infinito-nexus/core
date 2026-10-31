from __future__ import annotations

import json
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from crossposter import adapt
from crossposter.notify import Mail

if TYPE_CHECKING:
    from crossposter.sources import SourceItem

PLATFORMS = frozenset({"mastodon", "pixelfed", "peertube"})
MODES = frozenset({"review", "auto"})
VISIBILITIES = frozenset({"public", "unlisted", "private", "direct"})
MEDIA_FILTERS = frozenset({"any", "required", "none"})
REVIEW = "review"
LOOP_APPLICATION = "OpenPost"
RUNTIME = "<runtime>"


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Source:
    platform: str
    base_url: str
    account: str
    token: str


@dataclass(frozen=True)
class Filters:
    visibility: frozenset[str]
    exclude_replies: bool
    exclude_reblogs: bool
    tags: frozenset[str]
    media: str


@dataclass(frozen=True)
class Targets:
    accounts: tuple[str, ...]
    social_set: str


@dataclass(frozen=True)
class Route:
    name: str
    source: Source
    filters: Filters
    targets: Targets
    mode: str
    attribution: dict[str, str]

    def template(self, network: str) -> str:
        return self.attribution.get(network, self.attribution["default"])

    def refusal(self, item: SourceItem, opt_out_tag: str) -> str | None:
        tags = {
            tag.lower().lstrip("#")
            for tag in (*item.tags, *adapt.HASHTAG_RE.findall(item.text))
        }
        if opt_out_tag.lower() in tags:
            return "opt-out"
        if item.application == LOOP_APPLICATION:
            return "loop"
        if item.visibility not in self.filters.visibility:
            return "visibility"
        if self.filters.exclude_replies and item.in_reply_to:
            return "reply"
        if self.filters.exclude_reblogs and item.reblog:
            return "reblog"
        if self.filters.tags and not self.filters.tags & tags:
            return "tags"
        if self.filters.media == "required" and not item.media:
            return "media"
        if self.filters.media == "none" and item.media:
            return "media"
        return None


@dataclass(frozen=True)
class Retry:
    max_attempts: int
    base_seconds: float
    cap_seconds: float


@dataclass(frozen=True)
class OpenPostSettings:
    base_url: str
    host: str
    token: str
    workspace: str


@dataclass(frozen=True)
class Config:
    openpost: OpenPostSettings
    dsn: str
    mail: Mail | None
    heartbeat_file: str
    poll_interval_seconds: int
    opt_out_tag: str
    retry: Retry
    recipients: tuple[str, ...]
    routes: tuple[Route, ...]


def _require(condition: bool, route: str, field: str, message: str) -> None:
    if not condition:
        raise ConfigError(f"route '{route}': {field}: {message}")


def _secrets_file(path: str) -> Path:
    file = Path(path)
    _require(file.is_file(), RUNTIME, "secrets_file", f"{path} does not exist")
    return file


def _value(secrets: dict, key: str, owner: str, field: str) -> str:
    value = str(secrets.get(key) or "").strip()
    _require(bool(value), owner, field, "is missing from the secrets file")
    return value


def _mail(raw: dict | None, secrets: dict) -> Mail | None:
    if not raw:
        return None
    user = str(raw["user"])
    password = ""
    if user:
        password = _value(secrets, "mail_password", RUNTIME, "mail.password")
    return Mail(
        host=str(raw["host"]),
        port=int(raw["port"]),
        security=str(raw["security"]),
        user=user,
        password=password,
        sender=str(raw["sender"]),
    )


def _route(raw: dict, tokens: dict) -> Route:
    name = str(raw.get("name") or "")
    _require(bool(name), "<unnamed>", "name", "every route needs a name")
    source = raw.get("source") or {}
    platform = str(source.get("platform") or "")
    _require(
        platform in PLATFORMS,
        name,
        "source.platform",
        f"{platform!r} is not one of {sorted(PLATFORMS)}",
    )
    base_url = str(source.get("base_url") or "").rstrip("/")
    parts = urllib.parse.urlsplit(base_url)
    _require(
        parts.scheme == "https"
        or (parts.scheme == "http" and (parts.hostname or "").endswith(".onion")),
        name,
        "source.base_url",
        "must be an https:// URL, or http:// for an onion service",
    )
    account = str(source.get("account") or "")
    _require(bool(account), name, "source.account", "names no account")
    filters = raw.get("filters") or {}
    visibility = frozenset(filters.get("visibility") or [])
    _require(bool(visibility), name, "filters.visibility", "lists no visibility")
    _require(
        visibility <= VISIBILITIES,
        name,
        "filters.visibility",
        f"{sorted(visibility - VISIBILITIES)} are unknown",
    )
    media = str(filters.get("media") or "")
    _require(
        media in MEDIA_FILTERS,
        name,
        "filters.media",
        f"{media!r} is not one of {sorted(MEDIA_FILTERS)}",
    )
    targets = raw.get("targets") or {}
    accounts = tuple(str(account) for account in targets.get("accounts") or [])
    social_set = str(targets.get("social_set") or "")
    _require(
        bool(accounts) != bool(social_set),
        name,
        "targets",
        "name either accounts or one social_set",
    )
    mode = str(raw.get("mode") or REVIEW)
    _require(mode in MODES, name, "mode", f"{mode!r} is not one of {sorted(MODES)}")
    attribution = {
        str(key): str(value) for key, value in (raw.get("attribution") or {}).items()
    }
    _require(
        "default" in attribution,
        name,
        "attribution.default",
        "the default template is missing",
    )
    for network, template in attribution.items():
        _require(
            "{text}" in template,
            name,
            f"attribution.{network}",
            "the template must contain {text}",
        )
    return Route(
        name=name,
        source=Source(
            platform,
            base_url,
            account,
            _value(tokens, name, name, "source.token"),
        ),
        filters=Filters(
            visibility=visibility,
            exclude_replies=bool(filters.get("exclude_replies")),
            exclude_reblogs=bool(filters.get("exclude_reblogs")),
            tags=frozenset(
                str(tag).lower().lstrip("#") for tag in filters.get("tags") or []
            ),
            media=media,
        ),
        targets=Targets(accounts, social_set),
        mode=mode,
        attribution=attribution,
    )


def parse(raw: dict) -> Config:
    secrets = json.loads(_secrets_file(str(raw["secrets_file"])).read_text())
    tokens = dict(secrets.get("routes") or {})
    routes = tuple(_route(item, tokens) for item in raw.get("routes") or [])
    names = [route.name for route in routes]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ConfigError(f"route '{duplicates[0]}': name: is used more than once")
    retry = raw["retry"]
    openpost = raw["openpost"]
    return Config(
        openpost=OpenPostSettings(
            base_url=str(openpost["base_url"]),
            host=str(openpost["host"]),
            token=_value(secrets, "openpost_token", RUNTIME, "openpost.token"),
            workspace=str(openpost["workspace"]),
        ),
        dsn=_value(secrets, "database_dsn", RUNTIME, "database.dsn"),
        mail=_mail(raw.get("mail"), secrets),
        heartbeat_file=str(raw["heartbeat_file"]),
        poll_interval_seconds=int(raw["poll_interval_seconds"]),
        opt_out_tag=str(raw["opt_out_tag"]),
        retry=Retry(
            int(retry["max_attempts"]),
            float(retry["base_seconds"]),
            float(retry["cap_seconds"]),
        ),
        recipients=tuple(
            str(item) for item in (raw.get("notify") or {}).get("recipients") or []
        ),
        routes=routes,
    )


def load(path: str) -> Config:
    return parse(json.loads(Path(path).read_text()))
