# Administration

## Superuser Access

To query the cluster via the built-in `elastic` superuser execute the following on the server:

```bash
# Assuming the container name is elasticsearch
docker exec -it elasticsearch curl -u elastic "http://127.0.0.1:9200/_cluster/health?pretty"
```
