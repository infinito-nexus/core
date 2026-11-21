#!/usr/bin/env bash
set -euo pipefail

# Report the host load so the translator's crons can decide whether to start the
# translation lane, without touching Docker directly.

uptime
