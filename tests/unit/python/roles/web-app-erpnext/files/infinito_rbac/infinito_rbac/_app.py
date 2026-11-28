from __future__ import annotations

import importlib.util
import sys
from types import ModuleType
from unittest.mock import patch

from . import APP_PACKAGE

SHARED_MODULES = ("roles", "guard", "reclaim")


def _row_matches(row, key, value, parent):
    return all(
        expected is None or row[field] == expected
        for field, expected in (
            ("defkey", key),
            ("defvalue", value),
            ("parent", parent),
        )
    )


def defaults_module(frappe):
    """Args:
        frappe: the fake whose ``default_rows`` list of ``{parent, defkey,
            defvalue}`` dicts the module changes; ``session.user`` names its
            signed-in user.

    Returns:
        A ``frappe.defaults`` stand-in.
    """
    module = ModuleType("frappe.defaults")

    def add_default(key, value, parent, parenttype=None):
        frappe.default_rows.append({"parent": parent, "defkey": key, "defvalue": value})

    def clear_default(key=None, value=None, parent=None, name=None, parenttype=None):
        assert key or parent, "clear_default needs a key or a parent"
        frappe.default_rows[:] = [
            row
            for row in frappe.default_rows
            if not _row_matches(row, key, value, parent)
        ]

    def set_default(key, value, parent, parenttype="__default"):
        frappe.default_rows[:] = [
            row
            for row in frappe.default_rows
            if not _row_matches(row, key, None, parent)
        ]
        if value is not None:
            add_default(key, value, parent, parenttype)

    def set_user_default(key, value, user=None, parenttype=None):
        set_default(key, value, user or frappe.session.user, parenttype)

    module.add_default = add_default
    module.clear_default = clear_default
    module.set_default = set_default
    module.set_user_default = set_user_default
    return module


def app_modules(frappe):
    """Args:
        frappe: the fake every shared module binds as ``frappe``.

    Returns:
        Module name to module of the app package, its shared modules and
        ``frappe.defaults``, for ``patch.dict(sys.modules, ...)``.
    """
    defaults = defaults_module(frappe)
    package = ModuleType(APP_PACKAGE.name)
    package.__path__ = []
    modules = {APP_PACKAGE.name: package, "frappe.defaults": defaults}
    for name in SHARED_MODULES:
        spec = importlib.util.spec_from_file_location(
            f"{APP_PACKAGE.name}.{name}", APP_PACKAGE / f"{name}.py"
        )
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {**modules, "frappe": frappe}):
            spec.loader.exec_module(module)
        setattr(package, name, module)
        modules[module.__name__] = module
    return modules
