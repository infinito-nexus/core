"""Ensure the service provider's Company and the records ERPNext needs to quote,
order and invoice for it.

The site skips the setup wizard, so nothing else installs the warehouse type,
territory, unit and opportunity type the wizard would create. An existing
Company keeps its abbreviation, country and currency and only gains the records
it lacks; the global default company is set only while none is.

Runs on the stdin of the bench Python inside the ERPNext backend container and
prints one JSON line naming the Company and every record it created.

Environment:
    SITE_NAME: Frappe site to configure.
    COMPANY_NAME: name of the Company.
    COMPANY_ABBR: abbreviation ERPNext appends to the Company's account names.
    COMPANY_COUNTRY: the Company's country as ERPNext's country data names it;
        the Company's currency is the one that data assigns to it.
"""

import json
import os

import frappe
from frappe.geo.country_info import get_country_info
from frappe.utils import getdate

SITES_PATH = "/home/frappe/frappe-bench/sites"
TAX_GROUP = "Duties and Taxes"
TAX_ACCOUNTS = ("VAT 19%", "VAT 7%", "VAT 20%", "Reverse Charge", "Export")
FIXTURES = (
    ("Warehouse Type", "Transit", {"__newname": "Transit"}),
    (
        "Territory",
        "All Territories",
        {"territory_name": "All Territories", "is_group": 1},
    ),
    ("UOM", "Unit", {"uom_name": "Unit"}),
    ("Opportunity Type", "Sales", {"__newname": "Sales"}),
)
INVENTORY_KEYS = {
    "COMPANY_NAME": "service_provider.company.titel",
    "COMPANY_ABBR": "applications.web-app-erpnext.services.erpnext.company.abbr",
    "COMPANY_COUNTRY": "service_provider.company.address.country",
}


def required(name):
    """Return a non-empty operator input or stop the run.

    Args:
        name: environment variable carrying the input.

    Returns:
        The value without surrounding whitespace.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"{name} is empty: set {INVENTORY_KEYS[name]} in the inventory"
        )
    return value


def currency_of(country):
    """Return the currency ERPNext's country data assigns to a country.

    Args:
        country: country name as ERPNext's country data spells it.

    Returns:
        The ISO currency code.
    """
    currency = get_country_info(country).get("currency")
    if not currency:
        raise SystemExit(
            f"ERPNext knows no country {country!r}: set "
            f"{INVENTORY_KEYS['COMPANY_COUNTRY']} in the inventory to a country "
            "name from ERPNext's country list, such as 'Germany'"
        )
    return currency


def insert(doctype, fields):
    frappe.get_doc({"doctype": doctype, **fields}).insert(ignore_permissions=True)


def ensure_fixtures():
    created = []
    for doctype, name, fields in FIXTURES:
        if not frappe.db.exists(doctype, name):
            insert(doctype, fields)
            created.append(f"{doctype}: {name}")
    return created


def ensure_company(name, abbr, country, currency):
    if frappe.db.exists("Company", name):
        return []
    insert(
        "Company",
        {
            "company_name": name,
            "abbr": abbr,
            "country": country,
            "default_currency": currency,
        },
    )
    return [f"Company: {name}"]


def ensure_fiscal_year(company):
    today = getdate()
    covering = frappe.get_all(
        "Fiscal Year",
        filters={
            "disabled": 0,
            "year_start_date": ["<=", today],
            "year_end_date": [">=", today],
        },
        pluck="name",
    )
    for name in covering:
        companies = [
            row.company for row in frappe.get_doc("Fiscal Year", name).companies
        ]
        if not companies or company in companies:
            return []
    year = str(today.year)
    insert(
        "Fiscal Year",
        {
            "year": year,
            "year_start_date": f"{year}-01-01",
            "year_end_date": f"{year}-12-31",
        },
    )
    return [f"Fiscal Year: {year}"]


def ensure_tax_accounts(company, abbr):
    group = f"{TAX_GROUP} - {abbr}"
    if not frappe.db.exists("Account", group):
        raise SystemExit(
            f"Company {company!r} has no account group {group!r} for its taxes"
        )
    created = []
    for account_name in TAX_ACCOUNTS:
        account = f"{account_name} - {abbr}"
        if frappe.db.exists("Account", account):
            continue
        insert(
            "Account",
            {
                "account_name": account_name,
                "parent_account": group,
                "company": company,
                "account_type": "Tax",
                "is_group": 0,
            },
        )
        created.append(f"Account: {account}")
    return created


def ensure_default_cash_account(company):
    if frappe.db.get_value("Company", company, "default_cash_account"):
        return []
    for account_type in ("Cash", "Bank"):
        account = frappe.db.get_value(
            "Account",
            {"company": company, "account_type": account_type, "is_group": 0},
            "name",
            order_by="lft",
        )
        if account:
            frappe.db.set_value("Company", company, "default_cash_account", account)
            return [f"Default Cash Account: {account}"]
    raise SystemExit(f"Company {company!r} has neither a Cash nor a Bank account")


def ensure_default_company(company):
    defaults = frappe.get_single("Global Defaults")
    if defaults.default_company:
        return []
    country, currency = frappe.db.get_value(
        "Company", company, ["country", "default_currency"]
    )
    defaults.default_company = company
    defaults.country = country
    defaults.default_currency = currency
    defaults.save(ignore_permissions=True)
    return [f"Default Company: {company}"]


def main():
    site = os.environ["SITE_NAME"]
    name = required("COMPANY_NAME")
    abbr = required("COMPANY_ABBR")
    country = required("COMPANY_COUNTRY")
    currency = currency_of(country)

    frappe.init(site=site, sites_path=SITES_PATH)
    frappe.connect()
    try:
        created = ensure_fixtures()
        created += ensure_company(name, abbr, country, currency)
        company_abbr = frappe.db.get_value("Company", name, "abbr")
        created += ensure_fiscal_year(name)
        created += ensure_tax_accounts(name, company_abbr)
        created += ensure_default_cash_account(name)
        created += ensure_default_company(name)
        frappe.db.commit()
        frappe.clear_cache()
    finally:
        frappe.destroy()

    print(
        json.dumps(
            {
                "company": name,
                "abbr": company_abbr,
                "country": country,
                "currency": currency,
                "created": created,
            }
        )
    )


if __name__ == "__main__":
    main()
