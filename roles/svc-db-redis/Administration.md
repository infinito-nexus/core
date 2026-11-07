# Administration

## Admin Access

To administer the central Redis instance via the `default` user, execute the following on the stack host:

```bash
# Assuming the container name is redis
docker exec -it redis sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" exec redis-cli'
```

## Inspect the accepted passwords

```bash
docker exec -it redis sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" exec redis-cli ACL LIST'
```

Every shared consumer authenticates as `default`, so this is the only user. Its rule line carries one `#<sha256>` per accepted password: more than one means a deploy rotated `REDIS_PASSWORD` and has not retired the replaced password yet.

## Retire a replaced password by hand

```bash
docker exec -it redis sh -c 'printf "%s" ">$REDIS_PASSWORD" | REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli -x ACL SETUSER default resetpass'
docker exec -it redis sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" exec redis-cli CLIENT KILL USER default'
```

The first command leaves only the current password; the second makes every open connection authenticate again, since removing a password does not close the connections it opened.
