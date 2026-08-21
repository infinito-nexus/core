#!/bin/sh
# Tor container entrypoint.
#
# public flavor: exec tor directly against the bind-mounted torrc.
# chutney flavor: first bring up a private, offline Tor test network with
#   chutney inside this container (all nodes on 127.0.0.1), extract its
#   authority/testing lines into the file the rendered torrc %includes, then
#   exec the node tor joined to that private net. Descriptor publication and
#   rendezvous then run at localhost speed instead of over the public network.
set -eu

if [ "${TOR_FLAVOR}" = "chutney" ]; then
    net="hs-v3-min"
    conf=/run/tor/chutney-net.conf
    mkdir -p /run/tor

    echo "[tor-entrypoint] bringing up chutney private network '${net}'"
    # Exception: chutney creates its net/ state dir relative to the CWD, so
    # every call must run from /opt/chutney or the torrc grep below misses.
    cd /opt/chutney
    CHUTNEY_LISTEN_ADDRESS=127.0.0.1 \
        ./chutney init --net "${net}"
    ./chutney configure
    ./chutney start
    ./chutney wait_for_bootstrap

    grep -hE '^(TestingTorNetwork|DirAuthority|DirServer|AlternateDirAuthority) ' \
        net/nodes/*/torrc | sort -u >"${conf}"
    if [ ! -s "${conf}" ]; then
        echo "[tor-entrypoint] ERROR: ${conf} is empty — the node would silently join the public Tor network" >&2
        exit 1
    fi
    echo "[tor-entrypoint] wrote ${conf} ($(wc -l <"${conf}") line(s))"
    cd /
fi

exec tor "$@"
