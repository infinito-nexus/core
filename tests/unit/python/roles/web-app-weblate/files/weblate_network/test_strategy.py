from __future__ import annotations

import importlib
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Self

from ._stand_ins import (
    CALLBACK,
    CLEARNET,
    MIDDLEWARE_MODULE,
    MIDDLEWARE_MODULE_PATH,
    NETWORK_PACKAGE,
    ONION,
    SITE_URL,
    STRATEGY_MODULE_PATH,
    DisallowedHostError,
    FakeRequest,
    UpstreamStrategy,
    apply_override,
    load_shipped,
    upstream_settings,
)

LAYOUT = {
    "social_django/__init__.py": "",
    "social_django/strategy.py": (
        "class DjangoStrategy:\n"
        "    def __init__(self, request=None):\n"
        "        self.request = request\n"
    ),
    "social_django/utils.py": (
        "from importlib import import_module\n"
        "\n"
        "STRATEGY = {strategy!r}\n"
        "_module, _, _member = STRATEGY.rpartition('.')\n"
        "Strategy = getattr(import_module(_module), _member)\n"
        "\n"
        "\n"
        "def load_strategy(request=None):\n"
        "    return Strategy(request)\n"
    ),
    "weblate/__init__.py": "",
    "weblate/accounts/__init__.py": "",
    "weblate/accounts/strategy.py": (
        "from social_django.strategy import DjangoStrategy\n"
        "\n"
        "\n"
        "class WeblateStrategy(DjangoStrategy):\n"
        "    pass\n"
    ),
    "weblate/middleware.py": (
        "from social_django.utils import load_strategy\n"
        "\n"
        "\n"
        "class ProxyMiddleware:\n"
        "    def process_request(self, request):\n"
        "        return None\n"
    ),
}
LAYOUT_MODULES = (
    "social_django",
    "social_django.strategy",
    "social_django.utils",
    "weblate",
    "weblate.accounts",
    "weblate.accounts.strategy",
    "weblate.middleware",
)


def configured_strategy() -> str:
    """Return the ``SOCIAL_AUTH_STRATEGY`` the override hands social_django."""
    return apply_override(upstream_settings())["SOCIAL_AUTH_STRATEGY"]


class StandInPackages:
    """A disposable ``sys.path`` with the social_django/weblate import graph of 2026.9.

    ``social_django.utils`` resolves the strategy at import time, before it
    defines ``load_strategy``, and ``weblate.middleware`` imports
    ``load_strategy`` back, exactly as social_django/utils.py:12 and
    weblate/middleware.py:25 do.

    Args:
        strategy_source: the shipped strategy module copied onto the path.
        strategy: the dotted ``SOCIAL_AUTH_STRATEGY`` social_django resolves.
    """

    def __init__(self, strategy_source: Path, strategy: str):
        self.strategy_source = strategy_source
        self.strategy = strategy
        self.names = (
            *LAYOUT_MODULES,
            NETWORK_PACKAGE,
            strategy.rpartition(".")[0],
            MIDDLEWARE_MODULE,
        )

    def __enter__(self) -> Self:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        for rel, text in LAYOUT.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text.format(strategy=self.strategy), encoding="utf-8")
        package = root / NETWORK_PACKAGE
        package.mkdir()
        shutil.copy(self.strategy_source, package / self.strategy_source.name)
        shutil.copy(MIDDLEWARE_MODULE_PATH, package / MIDDLEWARE_MODULE_PATH.name)
        self._saved_path = list(sys.path)
        self._saved_modules = {name: sys.modules.pop(name, None) for name in self.names}
        sys.path.insert(0, str(root))
        importlib.invalidate_caches()
        return self

    def __exit__(self, *exc_info) -> None:
        for name in self.names:
            sys.modules.pop(name, None)
        for name, module in self._saved_modules.items():
            if module is not None:
                sys.modules[name] = module
        sys.path[:] = self._saved_path
        self._tmp.cleanup()


class TestStrategyImportsAtAppReady(unittest.TestCase):
    def test_social_django_resolves_the_strategy_without_weblate_middleware(
        self,
    ) -> None:
        with StandInPackages(STRATEGY_MODULE_PATH, configured_strategy()):
            utils = importlib.import_module("social_django.utils")
            self.assertEqual(utils.Strategy.__name__, "NetworkStrategy")
            self.assertNotIn(
                "weblate.middleware",
                sys.modules,
                "social_django.utils imports the strategy before it defines "
                "load_strategy, and weblate.middleware imports load_strategy "
                "back: the container dies on a circular ImportError",
            )

    def test_the_middleware_loads_once_apps_are_ready(self) -> None:
        with StandInPackages(STRATEGY_MODULE_PATH, configured_strategy()):
            importlib.import_module("social_django.utils")
            module = importlib.import_module(MIDDLEWARE_MODULE)
            upstream = importlib.import_module("weblate.middleware")
            self.assertTrue(
                issubclass(module.NetworkProxyMiddleware, upstream.ProxyMiddleware)
            )


class TestNetworkStrategy(unittest.TestCase):
    def setUp(self) -> None:
        self.module = load_shipped()["strategy"]

    def test_it_subclasses_upstream(self) -> None:
        self.assertTrue(issubclass(self.module.NetworkStrategy, UpstreamStrategy))

    def test_the_oidc_callback_follows_the_onion_request(self) -> None:
        strategy = self.module.NetworkStrategy(FakeRequest(ONION, secure=False))
        self.assertEqual(
            strategy.build_absolute_uri(CALLBACK),
            f"http://{ONION}{CALLBACK}",
            "the OIDC redirect_uri must name the vhost the login started on, "
            "or the session cookie set there never comes back",
        )
        self.assertFalse(strategy.request_is_secure())
        self.assertEqual(strategy.request_host(), ONION)
        self.assertIsNone(strategy.request_port())

    def test_the_oidc_callback_stays_on_clearnet_https(self) -> None:
        strategy = self.module.NetworkStrategy(FakeRequest(CLEARNET, secure=True))
        self.assertEqual(strategy.build_absolute_uri(CALLBACK), f"{SITE_URL}{CALLBACK}")
        self.assertTrue(strategy.request_is_secure())
        self.assertEqual(strategy.request_host(), CLEARNET)

    def test_an_explicit_port_is_reported(self) -> None:
        strategy = self.module.NetworkStrategy(
            FakeRequest("weblate:8080", secure=False)
        )
        self.assertEqual(strategy.request_host(), "weblate")
        self.assertEqual(strategy.request_port(), 8080)

    def test_a_host_outside_allowed_hosts_is_refused(self) -> None:
        strategy = self.module.NetworkStrategy(FakeRequest("evil.example", secure=True))
        with self.assertRaises(DisallowedHostError):
            strategy.build_absolute_uri(CALLBACK)

    def test_without_a_request_upstream_answers(self) -> None:
        strategy = self.module.NetworkStrategy(None)
        self.assertEqual(strategy.build_absolute_uri(CALLBACK), CALLBACK)
        self.assertTrue(strategy.request_is_secure())
        self.assertEqual(strategy.request_host(), CLEARNET)
        self.assertIsNone(strategy.request_port())


if __name__ == "__main__":
    unittest.main()
