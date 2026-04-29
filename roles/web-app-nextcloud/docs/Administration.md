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
