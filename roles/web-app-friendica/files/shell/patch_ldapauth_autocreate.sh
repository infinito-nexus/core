#!/usr/bin/env bash
#
# Patch the upstream friendica-addons/ldapauth `ldap_createaccount` so
# the autocreate path returns the user-row shape the `authenticate`
# hook expects.
#
# Upstream returns the bare `User::create()` result, which is
# `['user' => UserRow, 'password' => '']`. The hook then evaluates
# `if (!empty($user['uid']))` and silently bails out — first-login
# users get inserted into `friendica.user` but never receive
# `authenticated = 1`, so /network keeps serving the login form
# instead of starting a session. We unwrap `$user['user']` so the uid
# is visible to the hook.
#
# Idempotent: a second run sees the patched line and exits "ALREADY".
# Retries are safe across `compose up` restarts because the addon
# tree is image-baked, not volume-mounted, so the upstream content
# returns whenever the friendica image is re-pulled.
#
# Usage:
#   patch_ldapauth_autocreate.sh EXEC_PREFIX LDAPAUTH_PATH
#     EXEC_PREFIX     full container-exec command prefix as a single arg
#                     (typical: 'docker compose exec -T --user root
#                     friendica')
#     LDAPAUTH_PATH   absolute path of ldapauth.php inside the container
set -euo pipefail

EXEC="$1"
P="$2"

ORIG="		return \$user;"
NEW="		return \$user['user'] ?? \$user;"

if $EXEC grep -qF "$NEW" "$P"; then
    echo "ALREADY"
    exit 0
fi

if ! $EXEC grep -qF "$ORIG" "$P"; then
    echo "NO-MATCH ldap_createaccount return-line shape changed upstream"
    exit 1
fi

# Use python to avoid shell-escaping the single quotes inside sed/awk
# replacement text — friendica image ships python3 via Composer base.
$EXEC python3 -c "
import sys
p='$P'
src=open(p).read()
new=src.replace('''$ORIG''', '''$NEW''', 1)
open(p, 'w').write(new)
print('PATCHED')
"
