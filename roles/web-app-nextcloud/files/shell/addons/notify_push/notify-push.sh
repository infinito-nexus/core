#!/bin/sh
# Param $1: "run" execs the daemon once the app placed an executable binary; "health" probes it
# Param NOTIFY_PUSH_APP_DIRECTORY: directory of the installed notify_push app
# Param PORT: port the daemon listens on
set -eu

app_directory="${NOTIFY_PUSH_APP_DIRECTORY:?NOTIFY_PUSH_APP_DIRECTORY env missing}"
port="${PORT:?PORT env missing}"
mode="${1:?usage: notify-push.sh run|health}"

arch="$(uname -m)"
case "$arch" in
  armv7*) arch=armv7 ;;
  aarch64*) arch=aarch64 ;;
esac
binary="${app_directory}/bin/${arch}/notify_push"

case "$mode" in
  run)
    until [ -x "$binary" ]; do
      echo "Waiting for the notify_push app to place an executable ${binary}"
      sleep 10
    done
    exec "$binary"
    ;;
  health)
    [ -x "$binary" ] || exit 0
    exec php -r "exit(@fsockopen('127.0.0.1', ${port}) ? 0 : 1);"
    ;;
  *)
    echo "usage: notify-push.sh run|health" >&2
    exit 64
    ;;
esac
