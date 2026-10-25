# Account providers

`github`, `gitea` and `gitlab` are built in and need no file here. Declare any
other external service as `<provider>.yml` with its base URL and API flavour:

```yaml
---
base_url: https://example.com
flavour: gitea
```

A declared provider is then usable in a firewall rule as
`account(<provider>/<label>)`, where the label is the logical account slot the
provisioner or the inventory resolves to a real username.
