#!/bin/sh
# Inputs (environment):
#   JITSI_REALIGN_AUTH_DOMAIN      XMPP auth domain that owns the service accounts
#   JITSI_REALIGN_FOCUS_PASSWORD   declared password of focus@<auth domain>
#   JITSI_REALIGN_JVB_PASSWORD     declared password of jvb@<auth domain>
#   JITSI_REALIGN_JIGASI_PASSWORD  declared password of jigasi@<auth domain>
#   JITSI_REALIGN_JIBRI_PASSWORD   declared password of jibri@<auth domain>
# Output: one [CHANGED] line per account on stdout, [FAIL] plus the prosody error on stderr.
# Exit: 0 when every account carries the declared password, 1 otherwise.
set -eu

PROSODY_CFG=/config/prosody.cfg.lua

prosody_shell() {
    prosodyctl --config "$PROSODY_CFG" shell "$@" 2>&1
}

realign() {
    user="$1"
    password="$2"
    jid="${user}@${JITSI_REALIGN_AUTH_DOMAIN}"
    if [ -z "$password" ]; then
        echo "[FAIL] ${jid}: no password supplied" >&2
        return 1
    fi
    if output=$(prosody_shell user password "$jid" "$password"); then
        echo "[CHANGED] ${jid} now carries the declared password"
        return 0
    fi
    case $(printf '%s' "$output" | tail -n 1) in
    *"No such user"*)
        output=$(prosody_shell user create "$jid" "$password") && {
            echo "[CHANGED] ${jid} was registered with the declared password"
            return 0
        }
        case $(printf '%s' "$output" | tail -n 1) in
        *"User exists"*)
            if output=$(prosody_shell user password "$jid" "$password"); then
                echo "[CHANGED] ${jid} now carries the declared password"
                return 0
            fi
            ;;
        esac
        ;;
    esac
    echo "[FAIL] ${jid}: $(printf '%s' "$output" | tail -n 1)" >&2
    return 1
}

realign focus "$JITSI_REALIGN_FOCUS_PASSWORD"
realign jvb "$JITSI_REALIGN_JVB_PASSWORD"
realign jigasi "$JITSI_REALIGN_JIGASI_PASSWORD"
realign jibri "$JITSI_REALIGN_JIBRI_PASSWORD"
