# TODO

- Verify in a swarm cluster that the `force_bridge` upstream actually reaches the gateway: openresty resolves `host.docker.internal` to the host gateway, while `svc-ai-litellm` publishes `{{ DOCKER_BIND_HOST }}:8081:4000`. On a real host `DOCKER_BIND_HOST` is `127.0.0.1`, and the assumption is that `docker stack deploy` drops the bind IP from the short port syntax and publishes on all interfaces via the routing mesh. If that assumption fails, publish the gateway port in host mode (long syntax) or give openresty a `litellm` consumer flag instead.

- Disable/prune path: `provides: litellm_ui` makes `expand_service_tokens('web-app-litellm')` expand to `services.litellm_ui.*`, so disabling the UI role does not clear its `services.litellm` consumer contract; the gateway stays force-loaded until that flag is flipped manually or the expander learns about redirected consumer contracts.

- Persona flows: `PERSONA_ADMINISTRATOR_BLOCKED` / `PERSONA_BIBER_BLOCKED` are set because the LiteLLM admin UI has no platform-user concept; it authenticates with its own `UI_USERNAME`/`UI_PASSWORD` pair from `svc-ai-litellm`. Add an administrator login flow once the UI credential is wired into the Playwright env, and an SSO path once the role gains an oauth2-proxy sidecar slot.
- SSO: `services.sso` is opted out; the UI is guarded by the proxy plus LiteLLM's own login. Revisit when a proxy-level SSO gate for stackless roles exists.
