# Administration

## Server mode

In `server` mode the linuxserver image generates one config per peer under
`/config/peer<N>/` inside the container volume. Inspect or hand a peer its config:

```bash
# List generated peers
container exec <wireguard-container> ls /config

# Print peer1's config (and QR code, if LOG_CONFS=true, in the container logs)
container exec <wireguard-container> cat /config/peer1/peer1.conf
```

Increase the peer count by raising `services.wireguard.server.peers` and redeploying;
the image creates the new peer directories on next start.

## Client mode

### Create client keys (manual peer)

```bash
wg_private_key="$(wg genkey)"
wg_public_key="$(echo "$wg_private_key" | wg pubkey)"
echo "PrivateKey:   $wg_private_key"
echo "PublicKey:    $wg_public_key"
echo "PresharedKey: $(wg genpsk)"
```

### Activate a client config

Drop the client config into the container's config volume and (re)start it:

```bash
container exec -i <wireguard-container> sh -c 'mkdir -p /config/wg_confs && cat > /config/wg_confs/wg0.conf' < wg0.conf
container restart <wireguard-container>
```

### Check status

```bash
container exec <wireguard-container> wg show
```

## NAT (client behind NAT)

When the `nat` flavor is set the role applies the legacy firewalled rules on the host:

```bash
iptables -A FORWARD -i wg0-client -j ACCEPT
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
```

Adjust the interfaces via `services.wireguard.client.nat_in_interface` /
`services.wireguard.client.nat_out_interface`.

## Further Resources

- [WireGuard Documentation](https://www.wireguard.com/)
- [linuxserver/wireguard image](https://docs.linuxserver.io/images/docker-wireguard/)
- [ArchWiki: WireGuard](https://wiki.archlinux.org/index.php/WireGuard)
- [Subnetting Basics](https://www.scaleuptech.com/de/blog/was-ist-und-wie-funktioniert-subnetting/)
