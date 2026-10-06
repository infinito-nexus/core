# nocheck: mirrored-unit-test - imports frappe at module level and runs inside the
# ERPNext image; the framework is not installable outside it
import hashlib
import json
import os
import re
from pathlib import Path

import frappe
from frappe.installer import update_site_config
from frappe.website.utils import clear_website_cache

SITE_NAME = os.environ["SITE_NAME"]
DESIGN_TITLE = os.environ["DESIGN_TITLE"]
DESIGN_LOGO_URL = os.environ["DESIGN_LOGO_URL"]
DESIGN_FAVICON_URL = os.environ["DESIGN_FAVICON_URL"]
DESIGN_THEME_CSS = os.environ["DESIGN_THEME_CSS"]

STATE_KEY = "infinito_design_state"
THEME_FILE = "infinito-design.css"
HEAD_OPEN = "<!--infinito-design-->"
HEAD_CLOSE = "<!--/infinito-design-->"
HEAD_BLOCK = re.compile(
    rf"\n?{re.escape(HEAD_OPEN)}.*?{re.escape(HEAD_CLOSE)}", re.DOTALL
)


def wanted_settings():
    """Return the branding fields the design owns right now.

    Returns:
        ``{"<DocType>::<field>": value}``; empty when the design, its title or
        its logo are switched off.
    """
    wanted = {}
    if DESIGN_TITLE:
        wanted["Website Settings::app_name"] = DESIGN_TITLE
    if DESIGN_LOGO_URL:
        wanted["Website Settings::app_logo"] = DESIGN_LOGO_URL
        wanted["Website Settings::splash_image"] = DESIGN_LOGO_URL
        wanted["Website Settings::favicon"] = DESIGN_FAVICON_URL
        wanted["Navbar Settings::app_logo"] = DESIGN_LOGO_URL
    return wanted


def converge_settings(wanted, state):
    """Write the owned fields and hand back the ones the design no longer owns.

    Args:
        wanted: Result of ``wanted_settings``.
        state: ``{"<DocType>::<field>": {"previous", "applied"}}`` of the last
            run, updated in place. A field leaves it with its previous value
            restored, unless somebody changed it after the design wrote it.

    Returns:
        ``True`` when a field was written.
    """
    changed = False
    for key in sorted({*wanted, *state}):
        doctype, field = key.split("::")
        current = frappe.db.get_single_value(doctype, field) or ""
        if key in wanted:
            entry = state.setdefault(key, {"previous": current})
            entry["applied"] = wanted[key]
            if current != wanted[key]:
                frappe.db.set_single_value(doctype, field, wanted[key])
                changed = True
            continue
        entry = state.pop(key)
        if current == entry["applied"]:
            frappe.db.set_single_value(doctype, field, entry["previous"])
            changed = True
    return changed


def theme_url():
    """Return the URL of the theme file, versioned by its content.

    Returns:
        The site-relative URL, or ``""`` when no theme is shipped.
    """
    if not DESIGN_THEME_CSS:
        return ""
    digest = hashlib.sha256(DESIGN_THEME_CSS.encode("utf-8")).hexdigest()[:12]
    return f"/files/{THEME_FILE}?v={digest}"


def converge_theme_file():
    """Write or remove the theme file in the public files of the site.

    Returns:
        ``True`` when the file changed.
    """
    path = Path(frappe.get_site_path("public", "files", THEME_FILE))
    current = path.read_text(encoding="utf-8") if path.exists() else None
    if not DESIGN_THEME_CSS:
        if current is None:
            return False
        path.unlink()
        return True
    if current == DESIGN_THEME_CSS:
        return False
    path.write_text(DESIGN_THEME_CSS, encoding="utf-8")
    return True


def converge_desk_include(url):
    """Link the theme file on the desk through the site config.

    Args:
        url: Result of ``theme_url``. Entries of other owners stay untouched.

    Returns:
        ``True`` when ``app_include_css`` changed.
    """
    config = frappe.get_file_json(frappe.get_site_path("site_config.json"))
    current = config.get("app_include_css") or []
    wanted = [entry for entry in current if THEME_FILE not in entry]
    if url:
        wanted.append(url)
    if wanted == current:
        return False
    update_site_config("app_include_css", wanted or "None")
    return True


def converge_website_head(url):
    """Link the theme file on the website pages through the head HTML setting.

    Args:
        url: Result of ``theme_url``. Only the marked block is replaced or
            removed; any other head HTML stays untouched.

    Returns:
        ``True`` when ``head_html`` changed.
    """
    current = frappe.db.get_single_value("Website Settings", "head_html") or ""
    wanted = HEAD_BLOCK.sub("", current)
    if url:
        link = f'{HEAD_OPEN}<link rel="stylesheet" href="{url}">{HEAD_CLOSE}'
        wanted = f"{wanted}\n{link}".lstrip("\n")
    if wanted == current:
        return False
    frappe.db.set_single_value("Website Settings", "head_html", wanted)
    return True


frappe.init(site=SITE_NAME, sites_path="/home/frappe/frappe-bench/sites")
frappe.connect()
changed = False
try:
    stored = frappe.db.get_default(STATE_KEY) or "{}"
    state = json.loads(stored)
    url = theme_url()
    results = [
        converge_settings(wanted_settings(), state),
        converge_theme_file(),
        converge_desk_include(url),
        converge_website_head(url),
    ]
    updated = json.dumps(state, sort_keys=True)
    if updated != stored:
        frappe.db.set_default(STATE_KEY, updated)
    changed = any(results) or updated != stored
    frappe.db.commit()
    if changed:
        frappe.clear_cache()
        clear_website_cache()
finally:
    frappe.destroy()

print("DESIGN_CHANGED" if changed else "DESIGN_UNCHANGED")
