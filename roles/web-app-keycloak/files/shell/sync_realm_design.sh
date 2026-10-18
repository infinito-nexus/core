#!/usr/bin/env bash
set -euo pipefail

# Param KEYCLOAK_EXEC_CONTAINER: command prefix that runs inside the Keycloak container, e.g. "container exec -i keycloak"
# Param KEYCLOAK_KCADM: path of kcadm inside the container, e.g. "/opt/keycloak/bin/kcadm.sh"
# Param KEYCLOAK_REALM: realm to reconcile
# Param KEYCLOAK_THEME: name of the corporate theme
# Param KEYCLOAK_THEME_ENABLED: true selects the theme where none is set, false releases it where it is set
# Param KEYCLOAK_DISPLAY_NAME_MANAGED: true reconciles the display name of the realm as well
# Param KEYCLOAK_DISPLAY_NAME: corporate display name, may be empty
# Param KEYCLOAK_DISPLAY_NAME_HTML: corporate HTML display name, may be empty
# Output: one line "[keycloak][design] updated: <realm>" or "[keycloak][design] unchanged: <realm>"

: "${KEYCLOAK_EXEC_CONTAINER:?missing KEYCLOAK_EXEC_CONTAINER}"
: "${KEYCLOAK_KCADM:?missing KEYCLOAK_KCADM}"
: "${KEYCLOAK_REALM:?missing KEYCLOAK_REALM}"
: "${KEYCLOAK_THEME:?missing KEYCLOAK_THEME}"
: "${KEYCLOAK_THEME_ENABLED:?missing KEYCLOAK_THEME_ENABLED}"
: "${KEYCLOAK_DISPLAY_NAME_MANAGED:?missing KEYCLOAK_DISPLAY_NAME_MANAGED}"
: "${KEYCLOAK_DISPLAY_NAME?missing KEYCLOAK_DISPLAY_NAME}"
: "${KEYCLOAK_DISPLAY_NAME_HTML?missing KEYCLOAK_DISPLAY_NAME_HTML}"

MARK_PREFIX='<div class="kc-logo-text"><span>'
MARK_SUFFIX='</span></div>'
EMPTY='""'

read -r -a exec_container <<<"${KEYCLOAK_EXEC_CONTAINER}"

current="$(
  "${exec_container[@]}" "${KEYCLOAK_KCADM}" get "realms/${KEYCLOAK_REALM}" \
    --fields loginTheme,accountTheme,adminTheme,displayName,displayNameHtml --format json |
    tr -d '\r' | sed -n '/^{/,$p'
)"

field() {
  python3 -c 'import json, sys; print(json.load(sys.stdin).get(sys.argv[1]) or "")' "$1" <<<"${current}"
}

changes=()

for key in loginTheme accountTheme adminTheme; do
  value="$(field "${key}")"
  if [[ "${KEYCLOAK_THEME_ENABLED}" == "true" ]]; then
    if [[ -z "${value}" ]]; then
      changes+=(-s "${key}=${KEYCLOAK_THEME}")
    fi
  elif [[ "${value}" == "${KEYCLOAK_THEME}" ]]; then
    changes+=(-s "${key}=${EMPTY}")
  fi
done

if [[ "${KEYCLOAK_DISPLAY_NAME_MANAGED}" == "true" ]]; then
  name="$(field displayName)"
  html="$(field displayNameHtml)"
  corporate=false
  if [[ "${html}" == "${MARK_PREFIX}"*"${MARK_SUFFIX}" ]]; then
    corporate=true
  elif [[ -z "${html}" && -n "${KEYCLOAK_DISPLAY_NAME}" && "${name}" == "${KEYCLOAK_DISPLAY_NAME}" ]]; then
    corporate=true
  fi

  if [[ "${KEYCLOAK_THEME_ENABLED}" == "true" && -n "${KEYCLOAK_DISPLAY_NAME}" ]]; then
    if [[ "${corporate}" == "true" || (-z "${name}" && -z "${html}") ]]; then
      if [[ "${name}" != "${KEYCLOAK_DISPLAY_NAME}" ]]; then
        changes+=(-s "displayName=${KEYCLOAK_DISPLAY_NAME}")
      fi
      if [[ "${html}" != "${KEYCLOAK_DISPLAY_NAME_HTML}" ]]; then
        if [[ -n "${KEYCLOAK_DISPLAY_NAME_HTML}" ]]; then
          changes+=(-s "displayNameHtml=${KEYCLOAK_DISPLAY_NAME_HTML}")
        else
          changes+=(-s "displayNameHtml=${EMPTY}")
        fi
      fi
    fi
  elif [[ "${corporate}" == "true" ]]; then
    changes+=(-s "displayName=${EMPTY}" -s "displayNameHtml=${EMPTY}")
  fi
fi

if [[ "${#changes[@]}" -eq 0 ]]; then
  echo "[keycloak][design] unchanged: ${KEYCLOAK_REALM}"
  exit 0
fi

"${exec_container[@]}" "${KEYCLOAK_KCADM}" update "realms/${KEYCLOAK_REALM}" "${changes[@]}"

echo "[keycloak][design] updated: ${KEYCLOAK_REALM}"
