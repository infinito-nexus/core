"""Lookup `playwright_parallel`: how the round runs its Playwright containers.

    lookup('playwright_parallel')                         -> the round's cap
    lookup('playwright_parallel', 'memory_mb', workers=N) -> one container's limit
    lookup('playwright_parallel', 'ram_fraction')         -> share of free RAM it may claim
    lookup('playwright_parallel', 'onion_cap')            -> browsers that may share Tor

A primary app opts its rows in through ``playwright.parallel`` in its
``meta/tests.yml``: a list with one entry per ``meta/variants.yml`` variant,
each the cap for the row that deploys that variant. The round's cap is the
smallest cap among ``PRIMARY_APPS`` at ``VARIANT_INDEX``, so a round runs in
parallel only when every app it was asked for opts in. A round without
primary apps, or with a primary app that declares no list, runs one container
at a time as it always did, and so does a round whose cap cannot be read: the
lookup decides the serial loop's ``when`` too, so it warns instead of raising.
The memory estimate, the RAM fraction and the Tor cap come from the sizing
``playwright_workers`` applies to every browser.
"""

from __future__ import annotations

import json
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.utils.display import Display

from plugins.lookup.playwright_workers import ONION_CAP, PER_WORKER_GB, RAM_FRACTION

PARALLEL = "playwright.parallel"


def primary_apps(value: Any) -> list[str]:
    """``PRIMARY_APPS`` as a list of app ids.

    Both CI drivers pass it as ``-e PRIMARY_APPS=["web-app-x"]``, which
    Ansible's key=value parser hands over as a string.

    Args:
        value: the templated ``PRIMARY_APPS``, a list or its JSON text.

    Returns:
        The app ids.

    Raises:
        AnsibleError: *value* is neither a list of app ids nor JSON for one.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise AnsibleError(f"PRIMARY_APPS is no JSON list: {value!r}") from exc
    if not isinstance(value, list) or not all(
        isinstance(app, str) and app for app in value
    ):
        raise AnsibleError(f"PRIMARY_APPS must be a list of app ids, got {value!r}.")
    return value


def validate_caps(app: str, caps: Any) -> list[int]:
    """*caps* as declared, once it is a list of positive integers.

    Args:
        app: the primary app whose ``meta/tests.yml`` declared *caps*.
        caps: the rendered ``playwright.parallel``.

    Returns:
        *caps*.

    Raises:
        AnsibleError: *caps* is not a list of positive integers.
    """
    if not isinstance(caps, list) or not all(
        isinstance(cap, int) and not isinstance(cap, bool) and cap >= 1 for cap in caps
    ):
        raise AnsibleError(
            f"{app}: {PARALLEL} in meta/tests.yml must be a list of positive "
            f"integers, one per variant, got {caps!r}."
        )
    return caps


def row_cap(app: str, caps: Any, variant: int) -> int:
    """Cap *app* declares for its row at *variant*.

    ``VARIANT_INDEX`` is the round index. The planner runs an app with fewer
    variants than the round on variant 0, or on a pinned variant, so that
    round is not the row the cap was declared for and runs serially.

    Args:
        app: the primary app whose ``meta/tests.yml`` declared *caps*.
        caps: the rendered ``playwright.parallel``, ``None`` when absent.
        variant: the round's ``VARIANT_INDEX``.

    Returns:
        The declared cap, or 1 when *app* declares none or has no entry for
        *variant*.

    Raises:
        AnsibleError: *caps* is not a list of positive integers.
    """
    if caps is None:
        return 1
    caps = validate_caps(app, caps)
    return caps[variant] if 0 <= variant < len(caps) else 1


class LookupModule(LookupBase):
    def run(
        self, terms, variables: dict[str, Any] | None = None, **kwargs
    ) -> list[Any]:
        if terms == ["memory_mb"]:
            return [int(PER_WORKER_GB * 1024 * int(kwargs["workers"]))]
        if terms == ["ram_fraction"]:
            return [RAM_FRACTION]
        if terms == ["onion_cap"]:
            return [ONION_CAP]
        if terms:
            raise AnsibleError(
                f"lookup('playwright_parallel'): unknown terms {terms!r}."
            )
        variables = variables or {}
        try:
            apps = primary_apps(self._templar.template(variables["PRIMARY_APPS"]))
            variant = int(self._templar.template(variables["VARIANT_INDEX"]))
            role_tests = lookup_loader.get(
                "role_tests", loader=self._loader, templar=self._templar
            )
            caps = [
                row_cap(
                    app,
                    role_tests.run([app, PARALLEL], variables=variables)[0],
                    variant,
                )
                for app in apps
            ]
        except (AnsibleError, KeyError, TypeError, ValueError) as exc:
            Display().warning(
                f"lookup('playwright_parallel'): {exc}; the round runs serially."
            )
            return [1]
        return [min(caps) if caps else 1]
