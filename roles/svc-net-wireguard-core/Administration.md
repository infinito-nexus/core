# Administration

## Client

### Setup wireguard

```bash
  pacman -S wireguard-tools
```

### Create Client Keys

```bash
  wg_private_key="$(wg genkey)"
  wg_public_key="$(echo "$wg_private_key" | wg pubkey)"
  echo "PrivateKey: $wg_private_key"
  echo "PublicKey: $wg_public_key"
  echo "PresharedKey: $(wg genpsk)"
```

### Activate Configuration

```bash
  cp /path/to/wg0.conf /etc/wireguard/wg0.conf
  systemctl enable wg-quick@wg0.service --now
```

### Check status

```bash
  systemctl status wg-quick@wg0.service
```

## Further Resources

- [ArchWiki: WireGuard](https://wiki.archlinux.org/index.php/WireGuard)
- [Subnetting Basics](https://www.scaleuptech.com/de/blog/was-ist-und-wie-funktioniert-subnetting/)
