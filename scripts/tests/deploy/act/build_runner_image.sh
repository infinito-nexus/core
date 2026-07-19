#!/usr/bin/env bash
# Build local/act-runner-fixed: the stock catthehacker act runner image with
# /var/run removed, so a recent Docker engine (28/29+) accepts act's job-setup
# content copy into /var/run/act instead of rejecting it as a path that escapes
# the /var/run -> /run symlink. Pass it to act via ACT_PLATFORM_IMAGE.
set -euo pipefail

printf 'FROM catthehacker/ubuntu:act-latest\nRUN rm -rf /var/run\n' |
	docker build -t local/act-runner-fixed:latest -
