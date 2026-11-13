from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.templating.jinja import rendered_or_raise

if TYPE_CHECKING:
    from collections.abc import Callable

TLS_OVERRIDES = ("enabled", "mode", "flavor")


def with_rendered_tls(
    app: dict, render: Callable[[Any], Any] | None, *, where: str
) -> dict:
    """Render the ``server.tls`` overrides that decide an application's TLS.

    Args:
        app: the application's configuration, rendered or not.
        render: renders an override in ``TLS_OVERRIDES`` that is still
            template text; None renders nothing.
        where: names the application in the error message.

    Returns:
        ``app`` without a ``server.tls`` mapping, else a copy whose overrides
        are rendered.

    Raises:
        AnsibleError: an override is still template text after ``render``.
    """
    server = app.get("server")
    tls = server.get("tls") if isinstance(server, dict) else None
    if not isinstance(tls, dict):
        return app
    rendered = {
        key: rendered_or_raise(tls[key], render, where=f"{where} server.tls.{key}")
        for key in TLS_OVERRIDES
        if key in tls
    }
    return {**app, "server": {**server, "tls": {**tls, **rendered}}}
