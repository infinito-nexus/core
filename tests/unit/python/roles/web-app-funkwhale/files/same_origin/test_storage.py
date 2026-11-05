from __future__ import annotations

import importlib.util
import posixpath
import sys
import unittest
from types import ModuleType, SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, quote, urlsplit

from . import PROJECT_ROOT

MODULE_PATH = (
    PROJECT_ROOT / "roles/web-app-funkwhale/files/python/same_origin/storage.py"
)
MEDIA_URL = "https://funkwhale.example.com/media/"
INTERNAL = "http://seaweedfs:8333"
EXPORT = "portability/ab/cd/ef/export.zip"


def storages_clean_name(name: str) -> str:
    """
    Args:
        name: storage name.

    Returns:
        The name the way storages.utils.clean_name of django-storages 1.14.6 rewrites it: normalised first, backslashes turned into slashes afterwards.
    """
    cleaned = posixpath.normpath(name).replace("\\", "/")
    if name.endswith("/") and not cleaned.endswith("/"):
        cleaned += "/"
    return "" if cleaned == "." else cleaned


def storages_signed_key(name: str) -> str:
    """
    Args:
        name: storage name a caller hands to S3Storage.url.

    Returns:
        The object key S3Storage.url of django-storages 1.14.6 signs for it, clean_name followed by the safe_join normalisation of _normalize_name.
    """
    return posixpath.normpath("/" + storages_clean_name(name)).lstrip("/")


class _StockS3Storage:
    def url(self, name, parameters=None, expire=None, http_method=None):
        method = http_method or "GET"
        return (
            f"{INTERNAL}/funkwhale/{storages_signed_key(name)}?X-Amz-Signature={method}"
        )


class _BadSignatureError(Exception):
    pass


class _SignatureExpiredError(_BadSignatureError):
    pass


class _Signing(ModuleType):
    def __init__(self) -> None:
        super().__init__("django.core.signing")
        self.BadSignature = _BadSignatureError
        self.SignatureExpired = _SignatureExpiredError
        self.max_ages: list[int] = []

    def dumps(self, value, salt):
        return f"{salt}|{value}"

    def loads(self, token, salt, max_age):
        self.max_ages.append(max_age)
        prefix = f"{salt}|"
        if not token.startswith(prefix):
            raise _BadSignatureError(token)
        if token.endswith("|expired"):
            raise _SignatureExpiredError(token)
        return token[len(prefix) :]


def stand_ins() -> dict[str, ModuleType]:
    """
    Returns:
        sys.modules entries standing in for django, django-storages and funkwhale's storage module.
    """
    conf = ModuleType("django.conf")
    conf.settings = SimpleNamespace(MEDIA_URL=MEDIA_URL, AWS_QUERYSTRING_EXPIRE=3600)
    core = ModuleType("django.core")
    signing = _Signing()
    core.signing = signing
    encoding = ModuleType("django.utils.encoding")
    encoding.filepath_to_uri = lambda path: quote(
        path.replace("\\", "/"), safe="/~!*()'"
    )
    funkwhale_storage = ModuleType("funkwhale_api.common.storage")
    funkwhale_storage.ASCIIS3Boto3Storage = _StockS3Storage
    storages_utils = ModuleType("storages.utils")
    storages_utils.clean_name = storages_clean_name
    return {
        "django": ModuleType("django"),
        "django.conf": conf,
        "django.core": core,
        "django.core.signing": signing,
        "django.utils": ModuleType("django.utils"),
        "django.utils.encoding": encoding,
        "funkwhale_api": ModuleType("funkwhale_api"),
        "funkwhale_api.common": ModuleType("funkwhale_api.common"),
        "funkwhale_api.common.storage": funkwhale_storage,
        "storages": ModuleType("storages"),
        "storages.utils": storages_utils,
    }


def load() -> ModuleType:
    """
    Returns:
        same_origin_storage imported over the stand-ins.
    """
    with mock.patch.dict(sys.modules, stand_ins()):
        spec = importlib.util.spec_from_file_location(
            "same_origin_storage", MODULE_PATH
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class TestSameOriginStorageUrl(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.storage = self.module.SameOriginS3Storage()

    def test_public_objects_resolve_on_the_app_origin(self):
        for name in (
            "attachments/ab/cd/ef/0f6c.png",
            "__sized__/attachments/ab/cd/ef/0f6c-crop-c0-5__0-5-200x200-95.png",
            "dynamic_preferences/ui__logo/infinito-design-ui__logo.png",
        ):
            with self.subTest(name=name):
                self.assertEqual(self.storage.url(name), MEDIA_URL + name)

    def test_public_urls_name_no_object_store(self):
        url = self.storage.url(
            "dynamic_preferences/ui__logo/infinito-design-ui__logo.png"
        )

        self.assertNotIn(INTERNAL, url)
        self.assertNotIn("X-Amz-", url)

    def test_the_music_library_stays_signed(self):
        self.assertEqual(
            self.storage.url("tracks/2026/11/04/song.mp3"),
            f"{INTERNAL}/funkwhale/tracks/2026/11/04/song.mp3?X-Amz-Signature=GET",
        )

    def test_a_name_climbing_out_of_its_prefix_stays_signed(self):
        for name in (
            "attachments/../tracks/song.mp3",
            "attachments/..\\tracks/song.mp3",
        ):
            with self.subTest(name=name):
                self.assertTrue(self.storage.url(name).startswith(INTERNAL))

    def test_presign_parameters_keep_the_signed_url(self):
        url = self.storage.url(
            "attachments/x.png", parameters={"ResponseContentDisposition": "attachment"}
        )

        self.assertTrue(url.startswith(INTERNAL))

    def test_a_presigned_method_keeps_the_signed_url(self):
        self.assertTrue(
            self.storage.url("attachments/x.png", http_method="PUT").startswith(
                INTERNAL
            )
        )

    def test_signed_url_signs_public_objects_too(self):
        self.assertEqual(
            self.storage.signed_url("attachments/x.png", "GET"),
            f"{INTERNAL}/funkwhale/attachments/x.png?X-Amz-Signature=GET",
        )

    def test_signed_url_signs_for_the_requested_method(self):
        self.assertTrue(
            self.storage.signed_url("attachments/x.png", "HEAD").endswith(
                "X-Amz-Signature=HEAD"
            )
        )

    def test_a_data_export_resolves_to_a_tokened_app_url(self):
        url = self.storage.url(EXPORT)
        parts = urlsplit(url)

        self.assertEqual(
            f"{parts.scheme}://{parts.netloc}{parts.path}", MEDIA_URL + EXPORT
        )
        self.assertNotIn(INTERNAL, url)
        self.assertTrue(
            self.module.token_names(parse_qs(parts.query)["token"][0], EXPORT)
        )


class TestKeys(unittest.TestCase):
    def setUp(self):
        self.module = load()

    def test_public_prefixes(self):
        for name in (
            "attachments/a.png",
            "__sized__/a.png",
            "dynamic_preferences/a.png",
        ):
            with self.subTest(name=name):
                self.assertTrue(self.module.is_public(name))

    def test_music_and_lookalike_prefixes_are_private(self):
        for name in (
            "tracks/a.mp3",
            "attachmentsX/a.png",
            "media/attachments/a.png",
            EXPORT,
            "",
        ):
            with self.subTest(name=name):
                self.assertFalse(self.module.is_public(name))

    def test_a_name_django_storages_would_rewrite_is_no_key(self):
        for name in (
            "attachments/../tracks/a.mp3",
            "attachments/..\\tracks/a.mp3",
            "attachments\\..\\..\\tracks/a.mp3",
            "attachments/./a.png",
            "attachments//a.png",
            "attachments/%2e%2e/tracks/a.mp3",
            "portability/../tracks/a.mp3",
            "portability/..\\tracks/a.mp3",
        ):
            with self.subTest(name=name):
                self.assertFalse(self.module.is_public(name))
                self.assertFalse(self.module.is_tokened(name))

    def test_every_public_name_is_the_key_django_storages_signs(self):
        for name in ("attachments/ab/cd/a.png", "dynamic_preferences/ui__logo/l.png"):
            with self.subTest(name=name):
                self.assertTrue(self.module.is_public(name))
                self.assertEqual(storages_signed_key(name), name)

    def test_only_data_exports_take_a_token(self):
        self.assertTrue(self.module.is_tokened(EXPORT))
        for name in ("tracks/a.mp3", "transcoded/a.ogg", "federation_cache/a.mp3"):
            with self.subTest(name=name):
                self.assertFalse(self.module.is_tokened(name))


class TestTokens(unittest.TestCase):
    def setUp(self):
        self.module = load()

    def test_a_token_names_only_its_own_export(self):
        token = self.module.token_for(EXPORT)

        self.assertTrue(self.module.token_names(token, EXPORT))
        self.assertFalse(
            self.module.token_names(token, "portability/xx/yy/zz/other.zip")
        )

    def test_a_forged_or_expired_token_names_nothing(self):
        for token in ("", "forged", self.module.token_for(EXPORT) + "|expired"):
            with self.subTest(token=token):
                self.assertFalse(self.module.token_names(token, EXPORT))

    def test_a_token_lives_as_long_as_a_presigned_url(self):
        self.module.token_names(self.module.token_for(EXPORT), EXPORT)

        self.assertEqual(self.module.signing.max_ages, [3600])


if __name__ == "__main__":
    unittest.main()
