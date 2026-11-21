# nocheck: mirrored-unit-test - runs inside `odoo shell`, which provides `env` and a live registry; the framework is not installable outside the Odoo image
"""Activate the platform language in Odoo and load its translations.

Env (from the container):
    ODOO_LANGUAGE  res.lang code to activate, such as ``en_GB``

Prints ``LANGUAGE_CHANGED`` when it activated the language and
``LANGUAGE_UNCHANGED`` when the language was active already.
"""

import os

env = globals()["env"]
code = os.environ["ODOO_LANGUAGE"]

lang = (
    env["res.lang"]
    .with_context(active_test=False)
    .search([("code", "=", code)], limit=1)
)
if not lang:
    raise SystemExit(f"Odoo knows no language with the code {code}")

if lang.active:
    print("LANGUAGE_UNCHANGED")
else:
    env["res.lang"]._activate_lang(code)
    env["ir.module.module"].search([("state", "=", "installed")])._update_translations(
        [code]
    )
    env.cr.commit()
    print("LANGUAGE_CHANGED")
