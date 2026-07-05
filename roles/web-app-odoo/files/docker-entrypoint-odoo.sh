#!/bin/bash
set -e

: "${ODOO_RC:?ODOO_RC must be set (odoo config path)}"

_db_param() {
  python3 - "$ODOO_RC" "$1" <<'PY'
import configparser, sys
c = configparser.ConfigParser(); c.read(sys.argv[1])
print(c["options"].get(sys.argv[2], ""))
PY
}

_schema_present() {
  python3 - "$ODOO_RC" <<'PY'
import configparser, sys, psycopg2
c = configparser.ConfigParser(); c.read(sys.argv[1])
o = c["options"]
conn = psycopg2.connect(
    host=o.get("db_host"), port=o.get("db_port", "5432"),
    user=o.get("db_user"), password=o.get("db_password"),
    dbname=o.get("db_name"),
)
cur = conn.cursor()
cur.execute("SELECT to_regclass('public.ir_module_module')")
present = cur.fetchone()[0] is not None
conn.close()
sys.exit(0 if present else 1)
PY
}

if [ -n "${ODOO_INIT_MODULES:-}" ]; then
  wait-for-psql.py \
    --db_host "$(_db_param db_host)" --db_port "$(_db_param db_port)" \
    --db_user "$(_db_param db_user)" --db_password "$(_db_param db_password)" \
    --timeout 120
  if ! _schema_present; then
    echo "[odoo-entrypoint] empty database -> installing core modules: ${ODOO_INIT_MODULES}"
    odoo --no-http --database="$(_db_param db_name)" \
      --init="${ODOO_INIT_MODULES}" --stop-after-init
  fi
fi

exec /entrypoint.sh "$@"
