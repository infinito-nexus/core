#!/bin/sh
# Param: $1 - build: bake the chutney network into the checkout at image build time
#             run: start that network on the node holding its address, else join it
# Param: build $2 - chutney checkout
# Param: build $3 - network name
# Param: build $4 - IPv4 address every node reaches the network on
# Param: build $5 - port bases as <name>=<port> pairs, named after chutney's <name>_base
# Param: build $6 - ports one base hands out, one per chutney node
# Param: run $2 - chutney checkout
# Param: run $3 - IPv4 address the network listens on
# Param: run $4 - file the node torrc includes
set -eu

fail() {
    echo "[tor-chutney] ERROR: $*" >&2
    exit 1
}

build() {
    checkout=$1
    net=$2
    address=$3
    bases=$4
    span=$5
    tornet="${checkout}/lib/chutney/TorNet.py"
    for base in ${bases}; do
        name=${base%%=*}
        port=${base#*=}
        sed -i "s/^\( *self\.${name}_base: int = \)[0-9][0-9]*$/\1${port}/" "${tornet}"
        grep -qx " *self\.${name}_base: int = ${port}" "${tornet}" ||
            fail "${tornet} sets no ${name}_base to move to ${port}"
    done
    cd "${checkout}"
    CHUTNEY_LISTEN_ADDRESS="${address}" ./chutney init --net "${net}"
    ./chutney configure
    set -- net/nodes/*/torrc
    [ -f "$1" ] || fail "${net} configured no node"
    [ "$#" -le "${span}" ] ||
        fail "${net} has $# nodes, more than the ${span} ports one base hands out"
    for torrc in "$@"; do
        echo "NumCPUs 1" >>"${torrc}"
    done
    grep -hE '^(TestingTorNetwork|DirAuthority|DirServer|AlternateDirAuthority) ' "$@" |
        sort -u >chutney-net.conf
    grep -qE '^(DirAuthority|DirServer|AlternateDirAuthority) ' chutney-net.conf ||
        fail "${net} carries no authority line, so every node would join the public Tor network"
}

run() {
    checkout=$1
    address=$2
    conf=$3
    mkdir -p "$(dirname "${conf}")"
    cp "${checkout}/chutney-net.conf" "${conf}"
    if python3 -c 'import socket, sys; s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect((sys.argv[1], 9)); sys.exit(s.getsockname()[0] != sys.argv[1])' "${address}" 2>/dev/null; then
        echo "[tor-chutney] ${address} is on this node: starting the chutney network"
        cd "${checkout}"
        rm -f net/nodes/*/pid
        ./chutney start
        ./chutney wait_for_bootstrap
    else
        echo "[tor-chutney] joining the chutney network on ${address}"
    fi
}

command=$1
shift
case "${command}" in
build) build "$@" ;;
run) run "$@" ;;
*) fail "unknown command ${command}" ;;
esac
