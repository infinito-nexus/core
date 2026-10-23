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

Every deploy checks this before the PDS starts: [pds_migrations.js](files/javascript/pds_migrations.js) runs in the pinned image against `bluesky_pds_data` and compares the migrations applied to `account.sqlite`, `sequencer.sqlite`, `did_cache.sqlite` and every actor store with the migrations the pinned `@atproto/pds` ships.

- When the data carries a migration the pinned image does not know, the deploy stops and names the pinned version, the version recorded in the volume and the unknown migrations.
- When the check passes, the pinned version is recorded in `infinito-pds-version` in the volume. Data written before that record existed is reported as written by a PDS newer than the pin.
- You MUST NOT lower `services.pds.version` on its own.
- To roll back, you MUST restore the `bluesky_pds_data` volume from the backup generation taken before the update and pin the old version in the same step. Follow [A single volume](../svc-bkp-volume-2-local/README.md#a-single-volume) for the restore.
- That backup generation exists only when `svc-bkp-volume-2-local` is deployed and `MODE_BACKUP` is enabled.
- The restore discards everything the PDS stored after the update.

## Debugging

- Websocket: [piehost.com](https://piehost.com/websocket-tester)
- Instance: [bsky-debug.app](https://bsky-debug.app)

Initial setup: no top-level domain.
