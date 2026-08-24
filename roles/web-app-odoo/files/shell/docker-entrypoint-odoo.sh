#!/bin/bash
set -e

: "${ODOO_RC:?ODOO_RC must be set (odoo config path)}"
: "${ODOO_UPDATE_MARKER:?ODOO_UPDATE_MARKER must be set (odoo update marker path)}"

_db_param() {
  python3 - "$ODOO_RC" "$1" <<'PY'
import configparser, sys
c = configparser.ConfigParser(); c.read(sys.argv[1])
print(c["options"].get(sys.argv[2], ""))
PY
}

_guarded_bootstrap() {
  python3 - "$ODOO_RC" "$ODOO_INIT_MODULES" "$ODOO_UPDATE_MARKER" <<'PY'
import configparser, os, subprocess, sys, psycopg2
rc, modules, marker = sys.argv[1], sys.argv[2], sys.argv[3]
c = configparser.ConfigParser(); c.read(rc)
o = c["options"]
db = o.get("db_name")
conn = psycopg2.connect(
    host=o.get("db_host"), port=o.get("db_port", "5432"),
    user=o.get("db_user"), password=o.get("db_password"),
    dbname=db,
)
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT pg_advisory_lock(hashtext('odoo_bootstrap_init'))")
try:
    cur.execute("SELECT to_regclass('public.ir_module_module')")
    if cur.fetchone()[0] is None:
        print("[odoo-entrypoint] empty database -> installing core modules: %s" % modules, flush=True)
        subprocess.run(
            ["odoo", "--no-http", "--database=%s" % db,
             "--init=%s" % modules, "--stop-after-init"],
            check=True,
        )
    elif marker and os.path.exists(marker):
        print("[odoo-entrypoint] update marker present -> `-u all` before serving", flush=True)
        subprocess.run(
            ["odoo", "--no-http", "--database=%s" % db,
             "-u", "all", "--stop-after-init"],
            check=True,
        )
        os.remove(marker)
finally:
    cur.execute("SELECT pg_advisory_unlock(hashtext('odoo_bootstrap_init'))")
    conn.close()
PY
}

if [ -n "${ODOO_INIT_MODULES:-}" ]; then
  wait-for-psql.py \
    --db_host "$(_db_param db_host)" --db_port "$(_db_param db_port)" \
    --db_user "$(_db_param db_user)" --db_password "$(_db_param db_password)" \
    --timeout 120
  _guarded_bootstrap
fi

exec /entrypoint.sh "$@"
