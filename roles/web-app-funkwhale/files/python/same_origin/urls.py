from __future__ import annotations

import mimetypes
from types import SimpleNamespace

from config.urls import urlpatterns as funkwhale_urlpatterns
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage
from django.http import HttpResponse
from django.urls import re_path
from django.views.decorators.http import require_safe
from funkwhale_api.music.views import get_file_path
from same_origin_storage import is_public, is_tokened, token_names


@require_safe
def serve(request, name):
    """
    Args:
        request: the request the front nginx forwards for /media/<name>.
        name: storage name of the requested object.

    Returns:
        An empty response whose X-Accel-Redirect is funkwhale's get_file_path of the object's URL signed for the internal endpoint and the request method.

    Raises:
        PermissionDenied: the name is neither a public key nor a tokened key whose token query names it.
    """
    tokened = is_tokened(name) and token_names(request.GET.get("token", ""), name)
    if not (is_public(name) or tokened):
        raise PermissionDenied(name)
    response = HttpResponse(
        content_type=mimetypes.guess_type(name)[0] or "application/octet-stream"
    )
    response["X-Accel-Redirect"] = get_file_path(
        SimpleNamespace(url=default_storage.signed_url(name, request.method))
    )
    return response


urlpatterns = [re_path(r"^media/(?P<name>.+)$", serve), *funkwhale_urlpatterns]
