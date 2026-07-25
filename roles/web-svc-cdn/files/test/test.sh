#!/usr/bin/env bash
# E2E orchestrator for web-svc-cdn. Branches on the deployed CDN flavor:
#   internal - the one-shot npm-mirror build ran, so the served CDN root holds
#     the npm/ mirror tree (empty when no frontend-dep role is co-deployed).
#   external - front-proxy only, so no CDN compose stack may be deployed.
# Variables sourced from test.env.j2 by test-e2e-cli.
set -euo pipefail

: "${CDN_TEST_FLAVOR:?}"
: "${CDN_TEST_IS_STACK_HOST:?}"
: "${CDN_TEST_WEB_ROOT:?}"
: "${CDN_TEST_STACK_DIR:?}"

if [[ "${CDN_TEST_IS_STACK_HOST}" != "true" ]]; then
    echo "SKIP: not the stack host; web-svc-cdn only builds there"
    exit 0
fi

npm_dir="${CDN_TEST_WEB_ROOT%/}/npm"

case "${CDN_TEST_FLAVOR}" in
internal)
    if [[ ! -d "${npm_dir}" ]]; then
        echo "FAIL: internal flavor but the one-shot build left no npm mirror at ${npm_dir}"
        exit 1
    fi
    echo "OK: internal flavor built the npm mirror tree at ${npm_dir}"
    ;;
*)
    if [[ -d "${CDN_TEST_STACK_DIR}" ]]; then
        echo "FAIL: external flavor but the CDN build stack is deployed at ${CDN_TEST_STACK_DIR}"
        exit 1
    fi
    echo "OK: external flavor served without the build stack (no ${CDN_TEST_STACK_DIR})"
    ;;
esac

echo "ALL CHECKS PASSED"
