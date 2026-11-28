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

A model vendor (`flavour: model-vendor`) also lists the agent `runtimes` it
serves and its `login_hosts`. A workspace with `model_access: login` adds
exactly these hosts to its egress, and only for a runtime the vendor names;
in gateway mode they stay closed, and a deny rule of the agent's firewall role
removes any of them in both modes; every egress target is compared lowercase
and without a trailing dot, and L08 refuses any other spelling. Lint L08
accepts only exact login host names and refuses hosts that serve user content
(`claude.ai`, `chatgpt.com`). Codex signed in with a ChatGPT account talks to
`chatgpt.com`, which also serves the account's conversations and file uploads,
so `openai.yml` does not list it: a login-mode Codex VM works only with an
OpenAI API login until the proxy can admit a single path of that host.
