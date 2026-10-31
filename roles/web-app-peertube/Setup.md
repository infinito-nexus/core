# Setup Peertube

## Change Root Administrator Password

A fresh instance creates the local `root` account with the platform administrator's password.
To change it later:

```bash
docker exec -it -u peertube peertube npm run reset-password -- -u root
```
