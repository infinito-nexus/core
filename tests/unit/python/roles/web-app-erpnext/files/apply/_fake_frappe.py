"""In-memory stand-in for the slice of Frappe the ERPNext apply scripts call.

Records live in dicts keyed by doctype and name. Inserting a Company does what
ERPNext's controller does on a real site: it refuses a missing ``Transit``
warehouse type or a taken abbreviation, builds a minimal chart of accounts and
picks the default cash account from it.
"""

from __future__ import annotations

import copy
import datetime as dt
import io
import os
import runpy
import sys
from contextlib import redirect_stdout
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

TODAY = dt.date(2026, 10, 22)
COUNTRY_CURRENCIES = {"Germany": "EUR", "United States": "USD"}
CHILD_TABLES = {"Fiscal Year": ("companies",), "User": ("roles",)}
NAME_FIELDS = {
    "Company": "company_name",
    "Fiscal Year": "year",
    "Territory": "territory_name",
    "UOM": "uom_name",
    "User": "email",
}


class LinkValidationError(Exception):
    pass


class DuplicateEntryError(Exception):
    pass


def get_country_info(country):
    """Mirror ``frappe.geo.country_info.get_country_info``.

    Args:
        country: country name.

    Returns:
        The country's data; an unknown country yields only format defaults.
    """
    info = {"date_format": "dd-mm-yyyy", "time_format": "HH:mm:ss"}
    if country in COUNTRY_CURRENCIES:
        info["currency"] = COUNTRY_CURRENCIES[country]
    return info


def _matches(record, filters):
    for field, expected in filters.items():
        value = record.get(field)
        if isinstance(expected, list):
            operator, operand = expected
            if value is None:
                return False
            if operator == "<=" and not value <= operand:
                return False
            if operator == ">=" and not value >= operand:
                return False
        elif value != expected:
            return False
    return True


class FakeDoc:
    def __init__(self, frappe, doctype, values, *, single=False):
        object.__setattr__(self, "_frappe", frappe)
        object.__setattr__(self, "_single", single)
        object.__setattr__(self, "doctype", doctype)
        object.__setattr__(self, "flags", SimpleNamespace())
        tables = {table: [] for table in CHILD_TABLES.get(doctype, ())}
        object.__setattr__(self, "_values", {**tables, **values})

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return self._values.get(name)

    def __setattr__(self, name, value):
        self._values[name] = value

    def get(self, name):
        return self._values.get(name)

    def append(self, table, row):
        self._values[table].append(SimpleNamespace(**row))

    def insert(self, ignore_permissions=False):
        self._values["name"] = self._frappe.insert(self.doctype, self._values)
        return self

    def save(self, ignore_permissions=False):
        if self._single:
            self._frappe.singles[self.doctype] = copy.deepcopy(self._values)
        elif self._values.get("name"):
            self._frappe.records[self.doctype][self._values["name"]] = copy.deepcopy(
                self._values
            )
        else:
            self.insert(ignore_permissions)
        return self


class FakeDb:
    def __init__(self, frappe):
        self._frappe = frappe
        self.committed = False

    def _table(self, doctype):
        return self._frappe.records.get(doctype, {})

    def exists(self, doctype, name):
        if doctype == "DocType":
            return name in self._frappe.doctypes
        return name in self._table(doctype)

    def get_value(self, doctype, filters, fieldname, order_by=None):
        if isinstance(filters, str):
            record = self._table(doctype).get(filters)
        else:
            candidates = [
                r for r in self._table(doctype).values() if _matches(r, filters)
            ]
            if order_by:
                candidates.sort(key=lambda r: r[order_by])
            record = candidates[0] if candidates else None
        if record is None:
            return None
        if isinstance(fieldname, list):
            return tuple(record.get(field) for field in fieldname)
        return record.get(fieldname)

    def set_value(self, doctype, name, fieldname, value):
        self._table(doctype)[name][fieldname] = value

    def commit(self):
        self.committed = True

    def set_default(self, key, value):
        self._frappe.defaults[key] = value

    def get_default(self, key):
        return self._frappe.defaults.get(key)

    def table_exists(self, name):
        return name in self._frappe.tables


class FakeFrappe:
    def __init__(self):
        self.records = {}
        self.singles = {}
        self.defaults = {}
        self.doctypes = {"System Settings", "Global Defaults"}
        self.tables = set()
        self.calls = []
        self.db = FakeDb(self)

    def seed(self, doctype, name, **values):
        self.records.setdefault(doctype, {})[name] = {**values, "name": name}

    def init(self, site, sites_path):
        self.calls.append(("init", site, sites_path))

    def connect(self):
        self.calls.append(("connect",))

    def clear_cache(self):
        self.calls.append(("clear_cache",))

    def destroy(self):
        self.calls.append(("destroy",))

    def get_doc(self, doctype, name=None):
        if isinstance(doctype, dict):
            values = dict(doctype)
            return FakeDoc(self, values.pop("doctype"), values)
        if name is None:
            return self.get_single(doctype)
        return FakeDoc(self, doctype, copy.deepcopy(self.records[doctype][name]))

    def get_single(self, doctype):
        values = copy.deepcopy(self.singles.get(doctype, {}))
        return FakeDoc(self, doctype, values, single=True)

    def new_doc(self, doctype):
        return FakeDoc(self, doctype, {})

    def get_all(self, doctype, filters=None, pluck=None):
        rows = [
            r for r in self.db._table(doctype).values() if _matches(r, filters or {})
        ]
        return [row[pluck] for row in rows] if pluck else rows

    def insert(self, doctype, values):
        """Store a new record the way the doctype's naming rule names it.

        Args:
            doctype: the record's doctype.
            values: the record's fields, ``__newname`` for prompt-named doctypes.

        Returns:
            The record's name.
        """
        stored = copy.deepcopy(values)
        name = stored.pop("__newname", None) or self._name_of(doctype, stored)
        if name in self.db._table(doctype):
            raise DuplicateEntryError(f"{doctype} {name} exists")
        if doctype == "Company":
            self._validate_company(stored)
        if doctype == "Account" and not self.db.exists(
            "Account", stored["parent_account"]
        ):
            raise LinkValidationError(
                f"Could not find Parent Account: {stored['parent_account']}"
            )
        if doctype == "Fiscal Year":
            stored.setdefault("disabled", 0)
            for field in ("year_start_date", "year_end_date"):
                stored[field] = dt.date.fromisoformat(stored[field])
        self.records.setdefault(doctype, {})[name] = {**stored, "name": name}
        if doctype == "Company":
            self._create_chart(name, stored["abbr"])
        return name

    def _name_of(self, doctype, values):
        if doctype == "Account":
            abbr = self.records["Company"][values["company"]]["abbr"]
            return f"{values['account_name']} - {abbr}"
        return values[NAME_FIELDS[doctype]]

    def _validate_company(self, values):
        if not self.db.exists("Warehouse Type", "Transit"):
            raise LinkValidationError("Could not find Warehouse Type: Transit")
        taken = {company["abbr"] for company in self.db._table("Company").values()}
        if values["abbr"] in taken:
            raise LinkValidationError("Abbreviation already used for another company")

    def _create_chart(self, company, abbr):
        self.seed(
            "Account",
            f"Duties and Taxes - {abbr}",
            company=company,
            account_type="Tax",
            is_group=1,
            lft=30,
        )
        self.seed(
            "Account",
            f"Cash - {abbr}",
            company=company,
            account_type="Cash",
            is_group=0,
            lft=20,
        )
        self.records["Company"][company]["default_cash_account"] = f"Cash - {abbr}"

    def modules(self):
        """Return the ``sys.modules`` entries that make this object ``frappe``.

        Returns:
            Module name to module, for ``patch.dict(sys.modules, ...)``.
        """
        country_info = ModuleType("frappe.geo.country_info")
        country_info.get_country_info = get_country_info
        geo = ModuleType("frappe.geo")
        geo.country_info = country_info
        utils = ModuleType("frappe.utils")
        utils.getdate = lambda: TODAY
        return {
            "frappe": self,
            "frappe.geo": geo,
            "frappe.geo.country_info": country_info,
            "frappe.utils": utils,
        }


def run_script(path, frappe, env):
    """Run an apply script against a fake site.

    Args:
        path: the script to run as ``__main__``.
        frappe: the fake site it talks to.
        env: the complete environment the script sees.

    Returns:
        What the script printed.
    """
    out = io.StringIO()
    with (
        patch.dict(os.environ, env, clear=True),
        patch.dict(sys.modules, frappe.modules()),
        redirect_stdout(out),
    ):
        runpy.run_path(str(path), run_name="__main__")
    return out.getvalue()
