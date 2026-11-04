from __future__ import annotations

from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.utils.encoding import filepath_to_uri
from funkwhale_api.common.storage import ASCIIS3Boto3Storage
from storages.utils import clean_name

PUBLIC_PREFIXES = ("attachments/", "__sized__/", "dynamic_preferences/")
TOKENED_PREFIXES = ("portability/",)
TOKEN_SALT = "same_origin_storage.token"  # noqa: S105 - signing salt namespace, not a credential


def is_key(name: str) -> bool:
    """
    Args:
        name: storage name as a request or a caller passes it.

    Returns:
        True when clean_name returns the name unchanged and it holds neither a backslash nor a percent sign.
    """
    return "\\" not in name and "%" not in name and clean_name(name) == name


def is_public(name: str) -> bool:
    """
    Args:
        name: storage name of an object in the funkwhale bucket.

    Returns:
        True for a key under attachments/, __sized__/ or dynamic_preferences/.
    """
    return name.startswith(PUBLIC_PREFIXES) and is_key(name)


def is_tokened(name: str) -> bool:
    """
    Args:
        name: storage name of an object in the funkwhale bucket.

    Returns:
        True for a key under portability/.
    """
    return name.startswith(TOKENED_PREFIXES) and is_key(name)


def token_for(name: str) -> str:
    """
    Args:
        name: storage name of a tokened object.

    Returns:
        A token signed for the name.
    """
    return signing.dumps(name, salt=TOKEN_SALT)


def token_names(token: str, name: str) -> bool:
    """
    Args:
        token: the token query parameter of a download link.
        name: storage name the link asks for.

    Returns:
        True when the token was signed for the name at most AWS_QUERYSTRING_EXPIRE seconds ago.
    """
    try:
        issued = signing.loads(
            token, salt=TOKEN_SALT, max_age=settings.AWS_QUERYSTRING_EXPIRE
        )
    except signing.BadSignature:
        return False
    return issued == name


class SameOriginS3Storage(ASCIIS3Boto3Storage):
    def url(self, name, parameters=None, expire=None, http_method=None):
        """
        Args:
            name: storage name of the object.
            parameters: extra presign parameters.
            expire: presign lifetime in seconds.
            http_method: presigned HTTP method.

        Returns:
            MEDIA_URL plus the name for a public key, MEDIA_URL plus the name and a token query for a tokened key, the URL signed for the internal endpoint for any other name or whenever parameters or http_method are given.
        """
        if not parameters and http_method is None:
            if is_public(name):
                return settings.MEDIA_URL + filepath_to_uri(name)
            if is_tokened(name):
                query = urlencode({"token": token_for(name)})
                return f"{settings.MEDIA_URL}{filepath_to_uri(name)}?{query}"
        return super().url(name, parameters, expire, http_method)

    def signed_url(self, name: str, http_method: str) -> str:
        """
        Args:
            name: storage name of the object.
            http_method: HTTP method the URL is signed for.

        Returns:
            The object's URL signed for the internal endpoint and http_method.
        """
        return super().url(name, http_method=http_method)
