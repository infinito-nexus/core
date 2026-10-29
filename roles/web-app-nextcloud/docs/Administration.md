# Administration

Instructions for manual administrative operations like container login, config file edits, and post-update recovery actions.

## Modify Config 🔧

### Enter the Container

```bash
compose exec -it application /bin/sh
```

### Modify the Configuration

Inside the container, install a text editor and edit the config:

```bash
apk add --no-cache nano && nano config/config.php
```

## Logs

The logs you will find here on the host: **/var/lib/docker/volumes/nextcloud_data/_data/data/nextcloud.log**

## Talk TURN and STUN

When `services.talk.enabled` is true, Nextcloud Talk MUST use the dedicated `web-svc-coturn` service for STUN and TURN instead of the HPB port exposed by `web-app-nextcloud`.

Check these admin URLs after deployment:

- `/settings/admin/talk#signaling_server`
- `/settings/admin/talk#stun_server`
- `/settings/admin/talk#turn_server`

## Talk media

By default every Talk stream goes through `web-svc-coturn`, and the `talk` container publishes no media port. Set `services.talk.direct_media` to `true` in the inventory to let clients send their media to the Janus media server inside the `talk` container directly: Janus then announces `networks.internet.ip4` and publishes `services.talk.ports.public.relay` (UDP, default 61000-61999) on that address, and clients fall back to `web-svc-coturn` only when UDP to that range is blocked. The setting takes effect in compose mode with a bridged `talk` service that uses `web-svc-coturn` for TURN, and only while `networks.internet.ip4` is an address of the host itself.

Open the range for UDP in any firewall in front of the host. Each participant of a call holds one peer connection per participant, so all calls together get at most as many peer connections as the range has ports, and a call of N participants needs N² of them. Janus refuses a new peer connection once the range is used up. Docker starts one `docker-proxy` process per published port.

`templates/janus.jcfg.j2` replaces the `janus.jcfg` of the `nextcloud/aio-talk` image. Before every deploy the role reads `/supervisord.conf` and that file from the image and stops unless Janus is started with that file and its settings equal the template without `rtp_port_range`, `nat_1_1_mapping` and `keep_private_host`. Re-derive the template from the new image when that happens.
