from __future__ import annotations

import importlib.util
import re
import sys
import unittest
import urllib.parse
from types import ModuleType, SimpleNamespace
from unittest import mock

from utils.cache.files import read_text

from . import PROJECT_ROOT
from .test_same_origin_storage import EXPORT
from .test_same_origin_storage import load as load_storage

MODULE_PATH = (
    PROJECT_ROOT
    / "roles/web-app-funkwhale/files/python/same_origin/same_origin_urls.py"
)
NGINX_CONF = PROJECT_ROOT / "roles/web-app-funkwhale/templates/nginx.conf.j2"
SIGNED = (
    "http://seaweedfs:8333/funkwhale/dynamic_preferences/ui__logo/infinito%20logo.png"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
    "&X-Amz-Credential=funkwhale%2F20261104%2Fus-east-1%2Fs3%2Faws4_request"
    "&X-Amz-Date=20261104T120000Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host"
    "&X-Amz-Signature=0123abcd"
)


class _ForbiddenError(Exception):
    pass


class _HttpResponse(dict):
    def __init__(self, content_type: str) -> None:
        super().__init__()
        self.content_type = content_type


def funkwhale_get_file_path(audio_file) -> bytes:
    """
    Args:
        audio_file: an object whose url is an absolute object-store URL.

    Returns:
        The X-Accel-Redirect value funkwhale 2.0.13 builds for it, the nginx branch of api/funkwhale_api/music/views.py:606-631.
    """
    protocol, remainder = audio_file.url.split("://", 1)
    hostname, r_path = remainder.split("/", 1)
    path = protocol + "://" + hostname + "/" + urllib.parse.quote(r_path)
    return ("/_protected" + "/media/" + path).encode("utf-8")


def nginx_capture(accel_redirect: bytes) -> str:
    """
    Args:
        accel_redirect: the X-Accel-Redirect header value.

    Returns:
        $1 of `location ~ /_protected/media/(.+)` after nginx unescapes an X-Accel-Redirect URI that carries a %, src/http/ngx_http_parse.c:1897-1912 (ngx_http_parse_unsafe_uri, release-1.27.4).
    """
    uri = urllib.parse.unquote(accel_redirect.decode("utf-8"))
    return re.search(r"/_protected/media/(.+)", uri).group(1)


def nginx_location(uri: str) -> str:
    """
    Args:
        uri: a URI the front nginx routes.

    Returns:
        The body of the first regex location of nginx.conf.j2 that matches the URI.
    """
    blocks = re.findall(
        r"location ~ (\S+) \{(.*?)\n    \}", read_text(str(NGINX_CONF)), flags=re.DOTALL
    )
    for pattern, body in blocks:
        if re.search(pattern.strip('"'), uri):
            return body
    raise AssertionError(f"no regex location of the front nginx takes {uri}")


def nginx_rewrite(body: str, uri: str) -> str:
    """
    Args:
        body: a location body carrying one `rewrite <regex> <replacement> last;`.
        uri: the URI the location took.

    Returns:
        The URI nginx searches the locations again with.
    """
    pattern, replacement = re.search(r"rewrite (\S+) (\S+) last;", body).groups()
    return re.sub(pattern, re.sub(r"\$(\d)", r"\\\1", replacement), uri)


def load() -> tuple[ModuleType, mock.MagicMock, ModuleType]:
    """
    Returns:
        same_origin_urls imported over stand-ins for django and funkwhale, the default storage it signs with and the same_origin_storage it checks names with.
    """
    storage_module = load_storage()
    storage = mock.MagicMock()
    storage.signed_url.return_value = SIGNED
    files_storage = ModuleType("django.core.files.storage")
    files_storage.default_storage = storage
    exceptions = ModuleType("django.core.exceptions")
    exceptions.PermissionDenied = _ForbiddenError
    http = ModuleType("django.http")
    http.HttpResponse = _HttpResponse
    urls = ModuleType("django.urls")
    urls.re_path = lambda pattern, view: (pattern, view)
    decorators = ModuleType("django.views.decorators.http")
    decorators.require_safe = lambda view: view
    config_urls = ModuleType("config.urls")
    config_urls.urlpatterns = ["funkwhale-route"]
    music_views = ModuleType("funkwhale_api.music.views")
    music_views.get_file_path = funkwhale_get_file_path
    modules = {
        "config": ModuleType("config"),
        "config.urls": config_urls,
        "django": ModuleType("django"),
        "django.core": ModuleType("django.core"),
        "django.core.exceptions": exceptions,
        "django.core.files": ModuleType("django.core.files"),
        "django.core.files.storage": files_storage,
        "django.http": http,
        "django.urls": urls,
        "django.views": ModuleType("django.views"),
        "django.views.decorators": ModuleType("django.views.decorators"),
        "django.views.decorators.http": decorators,
        "funkwhale_api": ModuleType("funkwhale_api"),
        "funkwhale_api.music": ModuleType("funkwhale_api.music"),
        "funkwhale_api.music.views": music_views,
        "same_origin_storage": storage_module,
    }
    with mock.patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location("same_origin_urls", MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module, storage, storage_module


def get(token: str | None = None) -> SimpleNamespace:
    """
    Args:
        token: the token query parameter, None for none.

    Returns:
        A GET request as serve reads it.
    """
    return SimpleNamespace(method="GET", GET={} if token is None else {"token": token})


class TestServe(unittest.TestCase):
    def setUp(self):
        self.module, self.storage, self.names = load()
        self.name = "dynamic_preferences/ui__logo/infinito logo.png"

    def test_public_object_is_handed_to_nginx_with_its_signed_internal_url(self):
        response = self.module.serve(get(), self.name)

        self.storage.signed_url.assert_called_once_with(self.name, "GET")
        self.assertEqual(nginx_capture(response["X-Accel-Redirect"]), SIGNED)

    def test_a_head_request_is_signed_for_head(self):
        self.module.serve(SimpleNamespace(method="HEAD", GET={}), self.name)

        self.storage.signed_url.assert_called_once_with(self.name, "HEAD")

    def test_the_presign_query_survives_the_encoding(self):
        response = self.module.serve(get(), self.name)
        header = response["X-Accel-Redirect"].decode("utf-8")

        self.assertNotIn(
            "?", header, "an unencoded ? would split the args off before $1"
        )
        self.assertIn("%3FX-Amz-Algorithm", header)
        self.assertIn(
            "?X-Amz-Algorithm=AWS4-HMAC-SHA256",
            nginx_capture(response["X-Accel-Redirect"]),
        )

    def test_the_response_carries_the_object_type(self):
        response = self.module.serve(get(), self.name)

        self.assertEqual(response.content_type, "image/png")

    def test_the_music_library_is_not_served(self):
        with self.assertRaises(_ForbiddenError):
            self.module.serve(get(), "tracks/song.mp3")
        self.storage.signed_url.assert_not_called()

    def test_a_name_climbing_out_of_its_prefix_is_not_served(self):
        for name in (
            "attachments/../tracks/song.mp3",
            "attachments/..\\tracks/song.mp3",
            "__sized__/..\\..\\transcoded/a.ogg",
            "dynamic_preferences/%2e%2e/tracks/song.mp3",
        ):
            with self.subTest(name=name), self.assertRaises(_ForbiddenError):
                self.module.serve(get(), name)
        self.storage.signed_url.assert_not_called()

    def test_a_data_export_is_served_with_its_token(self):
        self.module.serve(get(self.names.token_for(EXPORT)), EXPORT)

        self.storage.signed_url.assert_called_once_with(EXPORT, "GET")

    def test_a_data_export_without_its_own_token_is_not_served(self):
        other = self.names.token_for("portability/xx/yy/zz/other.zip")
        for token in (None, "forged", other):
            with self.subTest(token=token), self.assertRaises(_ForbiddenError):
                self.module.serve(get(token), EXPORT)
        self.storage.signed_url.assert_not_called()

    def test_the_media_route_precedes_the_funkwhale_routes(self):
        self.assertEqual(
            self.module.urlpatterns,
            [(r"^media/(?P<name>.+)$", self.module.serve), "funkwhale-route"],
        )


class TestFrontNginx(unittest.TestCase):
    def test_protected_media_proxies_the_unescaped_capture_verbatim(self):
        body = nginx_location("/_protected/media/http://seaweedfs:8333/funkwhale/a")

        self.assertIn("internal;", body)
        self.assertIn("proxy_pass $1;", body)
        self.assertIn("proxy_set_header Host $proxy_host;", body)

    def test_protected_media_drops_the_forwarded_host(self):
        body = nginx_location("/_protected/media/http://seaweedfs:8333/funkwhale/a")

        self.assertIn('proxy_set_header X-Forwarded-Host "";', body)

    def test_a_relative_public_redirect_goes_back_through_the_api(self):
        uri = "/_protected/media/attachments/ab/cd/ef/0f6c.png"
        body = nginx_location(uri)
        rewritten = nginx_rewrite(body, uri)

        self.assertIn("internal;", body)
        self.assertEqual(rewritten, "/media/attachments/ab/cd/ef/0f6c.png")
        self.assertIn("proxy_pass   http://funkwhale-api;", nginx_location(rewritten))

    def test_every_served_prefix_reaches_the_api(self):
        for uri in (
            "/media/attachments/a.png",
            "/media/__sized__/a.png",
            "/media/dynamic_preferences/a.png",
            "/media/" + EXPORT,
        ):
            with self.subTest(uri=uri):
                self.assertIn("proxy_pass   http://funkwhale-api;", nginx_location(uri))


if __name__ == "__main__":
    unittest.main()
