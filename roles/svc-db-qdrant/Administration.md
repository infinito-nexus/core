# Administration

## Inspect collections

```bash
# Assuming the container name is qdrant
docker exec -it qdrant bash -lc 'exec 3<>/dev/tcp/127.0.0.1/6333; printf "GET /collections HTTP/1.0\r\n\r\n" >&3; cat <&3'
```
