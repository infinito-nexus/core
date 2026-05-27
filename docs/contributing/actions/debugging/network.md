# Network 🌐

When compose pulls hang, image builds fail to resolve registry manifests, `make install-lint` times out on a TLS handshake, or DNS lookups return surprising addresses, the cause is almost always one of three things: MTU mismatch, IPv6 misrouting, or DNS / proxy interference.

## Diagnose tool 🕵️

```bash
make diagnose-network
```

Runs [__main__.py](../../../../cli/contributing/network/diagnose/__main__.py) inside the running `infinito` container and produces a structured DNS / TCP / TLS / PMTU report against the standard infrastructure hosts (`github.com`, `ghcr.io`, `registry-1.docker.io`, `auth.docker.io`, `pypi.org`, `files.pythonhosted.org`, `registry.npmjs.org`, `objects.githubusercontent.com`, `raw.githubusercontent.com`), separately for IPv4 and IPv6 when available. Extra hosts can be appended via `INFINITO_NET_DEBUG_HOSTS="example.com api.example.org" make diagnose-network`.

On first run it self-installs `iputils-ping` + `iproute2` via the container's package manager (Debian / Ubuntu apt, Arch pacman, Fedora / CentOS / RHEL dnf). The installer waits up to two minutes for an apt-lock if a parallel deploy is running. IPv6 probes are auto-skipped when the bridge has no usable IPv6 default route.

For each host the script reports four signals:

| Signal | Means | Fails when |
|---|---|---|
| `DNS` | `socket.getaddrinfo` resolution time + returned addresses | resolver unreachable, no records, AAAA/A missing |
| `TCP` | `socket.connect` time to the resolved address on `:443` | routing missing, firewall drops, upstream not listening |
| `TLS` | `ssl.wrap_socket` handshake time, negotiated protocol, certificate CN | __MTU drops mid-handshake__, MITM cert mismatch, CA bundle missing, server-side issue |
| `PMTU` | largest ICMP-DF payload that survives (= path MTU − 28 bytes IP+ICMP header) | container lacks `ping` after auto-install (auto-skipped), or path drops every probe size |

The classic failure shape (`DNS [OK]`, `TCP [OK]`, `TLS [FAIL] TimeoutError after 8s`) is an __MTU mismatch__, not a TLS-layer bug. Small packets (TCP-SYN, DNS replies) survive; the larger TLS-ServerHello with the certificate chain is dropped silently because the path MTU is below the bridge MTU and ICMP-needs-frag is filtered upstream. When `auth.docker.io` is OK but `ghcr.io` / `registry-1.docker.io` time out, the chain-length difference between hosts (Cloudflare-fronted ≈ small chain, GitHub/AWS ≈ large chain) confirms MTU as the cause rather than a blanket TLS block.

DNS resolutions to `172.30.0.4` for hosts like `pypi.org` are intentional: the package-cache frontend overrides those names in `/etc/hosts`, so traffic terminates at the local registry mirror with `0.00s` DNS/TCP/TLS times instead of hitting the public registry.

## MTU 📦

Docker defaults to MTU 1500. If the host outbound interface uses a smaller MTU (e.g. due to VPN, tunnels, or jumbo-frame negotiation failure), packets MAY be dropped or fragmented and TLS handshakes time out mid-flight (see the diagnose tool's classic-failure shape above).

The local development compose stack SHOULD inherit the host Docker MTU automatically from `/etc/docker/daemon.json`. If auto-detection is unavailable or wrong, override it explicitly with `INFINITO_OUTER_NETWORK_MTU`.

Inspect the host MTUs:

```bash
ip link show docker0
ip link show eth0
```

Fix via `/etc/docker/daemon.json`:

```json
{"mtu": 1450}
```

Then restart Docker:

```bash
sudo systemctl restart docker
```

For a one-off local override of the compose bridge, regenerate `.env` with the desired value and recreate the stack cleanly:

```bash
INFINITO_OUTER_NETWORK_MTU=1400 make dotenv
make compose-down && make compose-up
```

A clean `down && up` is required after the change: `make compose-up` alone recreates the bridge but compose then re-attaches existing containers with dynamic IPs instead of the static `default.env` ones, which breaks CoreDNS.

## IPv6 🔢

If IPv6 is active but misconfigured, Docker MAY attempt to pull over IPv6 and fail.

```bash
ip -6 addr show
curl -6 https://registry-1.docker.io/v2/
```

The recommended way to disable IPv6 for local development is via Make:

```bash
make network-ipv6-disable
```

This also restarts `docker.service` and then calls `make network-refresh`, so the running Infinito development stack is recreated when one is active and the new setting reaches fresh container network namespaces.

To restore the original IPv6 settings afterwards:

```bash
make network-ipv6-restore
```

This restore path also restarts `docker.service` and then calls `make network-refresh`, so the running Infinito development stack is recreated when one is active and the restored setting reaches fresh container network namespaces.

You can also refresh the running local stack directly after host-level changes:

```bash
make network-refresh
```

Alternatively, disable IPv6 only in Docker via `/etc/docker/daemon.json`:

```json
{"ipv6": false}
```

## General Connectivity 🔌

```bash
ping -c 3 registry-1.docker.io
curl -v https://registry-1.docker.io/v2/
```

Check firewall rules, proxy settings, and DNS configuration. The `proxy env vars` and `CA bundle summary` sections of `make diagnose-network` surface the same information from inside the container.
