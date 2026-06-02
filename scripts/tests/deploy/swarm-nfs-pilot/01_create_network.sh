#!/usr/bin/env bash
set -euo pipefail

# MTU 1400: TLS ServerHello fragmentation drops on host PMTU < 1500.
docker network create \
	--driver bridge \
	--subnet 192.168.244.0/24 \
	--opt com.docker.network.driver.mtu=1400 \
	swarm-lab
