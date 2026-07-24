# Administration

## Admin Access

To administer the central Redis instance via the `default` user, execute the following on the stack host:

```bash
# Assuming the container name is redis
docker exec -it redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning
```

## Inspect a consumer ACL user

```bash
docker exec -it redis redis-cli -a "$REDIS_PASSWORD" --no-auth-warning ACL GETUSER <entity>
```

A consumer user named `<entity>` is restricted to keys matching `<entity>:*`.
