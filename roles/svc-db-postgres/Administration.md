# Administration

## Root Access

To access the database via the root account execute the following on the server:

```bash
# Assuming the container name is postgres
docker exec -it postgres psql -U postgres
```
