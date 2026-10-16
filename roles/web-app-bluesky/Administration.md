# Administration

## Create a user via POST

```bash
compose exec -T pds printenv PDS_ADMIN_PASSWORD \
  | sed 's/[\\"]/\\&/g; s/.*/user = "admin:&"/' \
  | curl --config - -X POST https://your-pds-domain/xrpc/com.atproto.server.createAccount \
      -H "Content-Type: application/json" \
      -d '{
            "email": "user@example.com",
            "handle": "username",
            "password": "securepassword123",
            "inviteCode": "optional-invite-code"
          }'
```

## Use pdsadmin

```bash
compose exec -it pds pdsadmin
compose exec -it pds pdsadmin account create-invite-code
```

## Roll back the PDS image

The PDS migrates its account database forward when it starts. An older image refuses a database that a newer image has migrated and stops with `corrupted migrations: previously executed migration ... is missing`.

- You MUST NOT lower `services.pds.version` on its own.
- To roll back, you MUST restore the `bluesky_pds_data` volume from the backup generation taken before the update and pin the old version in the same step. Follow [A single volume](../svc-bkp-volume-2-local/README.md#a-single-volume) for the restore.
- That backup generation exists only when `svc-bkp-volume-2-local` is deployed and `MODE_BACKUP` is enabled.
- The restore discards everything the PDS stored after the update.

## Debugging

- Websocket: [piehost.com](https://piehost.com/websocket-tester)
- Instance: [bsky-debug.app](https://bsky-debug.app)

Initial setup: no top-level domain.
