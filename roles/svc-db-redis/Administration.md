# Administration

## Admin Access

To administer the central Redis instance via the `default` user, execute the following on the stack host:

```bash
# Assuming the container name is redis
docker exec -it redis sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" exec redis-cli'
```

## List ACL users

```bash
docker exec -it redis sh -c 'REDISCLI_AUTH="$REDIS_PASSWORD" exec redis-cli ACL LIST'
```

Applications share the `default` user. The HA form adds only the `sentinel` and `haproxy-check` users.
