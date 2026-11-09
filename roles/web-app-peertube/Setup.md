# Setup Peertube

## Change Root Administrator Password

```bash
docker exec -it -u peertube peertube npm run reset-password -- -u root
```
