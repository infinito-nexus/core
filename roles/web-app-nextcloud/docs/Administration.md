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

When `services.talk.enabled` is true, Nextcloud Talk uses the dedicated `web-svc-coturn` service for STUN and TURN. `web-app-nextcloud` runs no TURN server of its own.

Check these admin URLs after deployment:

- `/settings/admin/talk#signaling_server`
- `/settings/admin/talk#stun_server`
- `/settings/admin/talk#turn_server`

## Talk high-performance backend

The high-performance backend and the recording server run as four services of the `web-app-nextcloud` stack. Each one is pinned in `meta/services.yml`, and the role renders every configuration file they read.

| Service | Component | Source | Configuration |
|---|---|---|---|
| `talk_signaling` | [nextcloud-spreed-signaling](https://github.com/strukturag/nextcloud-spreed-signaling) | upstream image `strukturag/nextcloud-spreed-signaling` at `services.talk_signaling.version` | `templates/signaling.conf.j2`, mounted as a secret at `/config/server.conf` |
| `talk` | [Janus](https://github.com/meetecho/janus-gateway) | built by the role from `services.talk.repository` at the tag `services.talk.ref` on `services.talk.image:services.talk.version`, see `files/Dockerfiles/Janus/Dockerfile` | `templates/janus.jcfg.j2`, mounted as a config at `/usr/local/etc/janus/janus.jcfg` |
| `talk_nats` | [NATS](https://nats.io) | official image `nats` at `services.talk_nats.version` | command line only |
| `talk_recording` | [nextcloud-talk-recording](https://github.com/nextcloud/nextcloud-talk-recording) | built by the role from `services.talk_recording.repository` at the tag `services.talk_recording.ref` on `services.talk_recording.image:services.talk_recording.version`, see `files/Dockerfiles/Recording/Dockerfile` | `templates/recording.conf.j2`, mounted as a secret at `/conf/recording.conf` |

How the services connect:

- The `proxy` service forwards `/standalone-signaling/` to `talk_signaling` on `services.talk_signaling.ports.internal.signaling`.
- `talk_signaling` reaches `talk_nats` at `nats://talk_nats:4222` and Janus at `ws://talk:8188`, or at `ws://host.docker.internal:8188` while Janus uses the host network.
- `talk_signaling` and `talk_recording` reach Nextcloud at its public URL, and `talk_recording` joins calls through the public `/standalone-signaling/` endpoint.
- Nextcloud reaches the recording server at `http://talk_recording:1234/`.

`credentials.talk_signaling_secret`, `credentials.talk_internal_secret` and `credentials.talk_recording_secret` reach the services only through the rendered files. The signaling session keys are derived from `credentials.talk_signaling_secret`, so they stay stable across deploys. `talk_signaling` runs as UID 850, `talk` as UID 1000, `talk_nats` as UID 65534 and `talk_recording` as UID 122, each with one swarm replica. In swarm mode all four join the stack network and share no network namespace, so swarm may schedule them on different nodes.

### Version updates

1. The `cron-update` workflow runs `python3 -m cli.contributing.update.docker`, which raises `services.talk_signaling.version` and `services.talk_nats.version` from their registries together with the base images `services.talk.version` and `services.talk_recording.version`, and opens an update pull request.
2. The same workflow runs `python3 -m cli.contributing.update.repository`, which raises `services.talk.ref` and `services.talk_recording.ref` to the newest semver tag of their git repositories.
3. A new `ref` or base `version` changes the build arguments in `templates/compose.yml.j2` and the image tag `<ref>-<version>`, so the next deploy rebuilds the image and replaces the container in compose mode or the task in swarm mode.
4. A new upstream release that changes its configuration format needs a change to the matching template, because no start script inside an image writes or rewrites these files.

### Switching from nextcloud/aio-talk

The first deploy of this layout replaces the `nextcloud/aio-talk` and `nextcloud/aio-talk-recording` containers:

- In compose mode `compose up --force-recreate --remove-orphans` recreates the `talk` and `talk_recording` services with the new images and starts `talk_signaling` and `talk_nats`.
- In swarm mode `docker stack deploy --prune` updates `nextcloud_talk` and `nextcloud_talk_recording` in place and creates the two new services.
- The signaling, internal and recording secrets keep their inventory values, so Nextcloud needs no reconfiguration. Calls drop while the containers are replaced.
- The TURN server bundled in `nextcloud/aio-talk` is gone together with `credentials.talk_turn_secret`, `services.talk.turn_server.onboard_enabled` and the `stun_turn`, `stun_turn_tls` and `relay` ports of `services.nextcloud`. Remove those keys from inventories that set them.

## Talk media

By default every Talk stream goes through `web-svc-coturn`, and Janus publishes no port. Set `services.talk.direct_media` to `true` in the inventory to let clients send their media to Janus directly: Janus then announces `networks.internet.ip4` as `nat_1_1_mapping`, takes its media ports from `services.talk.ports.public.relay` (UDP, default 61000-61999) and publishes them on that address, and clients fall back to `web-svc-coturn` only when UDP to that range is blocked. The setting takes effect in compose mode when `web-svc-coturn` provides TURN and `networks.internet.ip4` is an address of the host itself.

`services.talk.network_mode` decides how Janus reaches that range:

| Value | Janus |
|---|---|
| `bridge` | runs on the stack network and publishes the range on `networks.internet.ip4` |
| `host` | runs in the host network namespace and binds the range itself; compose mode only, the deploy stops in swarm mode |

With `host`, Janus also answers its websocket API on port 8188 of every host interface. Block that port in any firewall in front of the host.

Open the media range for UDP in any firewall in front of the host. Each participant of a call holds one peer connection per participant, so all calls together get at most as many peer connections as the range has ports, and a call of N participants needs N² of them. Janus refuses a new peer connection once the range is used up. With `bridge`, Docker starts one `docker-proxy` process per published port.
