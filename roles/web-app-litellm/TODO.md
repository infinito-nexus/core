# TODO

- Verify in a swarm cluster that the `force_bridge` upstream actually reaches the gateway: openresty resolves `host.docker.internal` to the host gateway, while `svc-ai-litellm` publishes `{{ DOCKER_BIND_HOST }}:8081:4000`. On a real host `DOCKER_BIND_HOST` is `127.0.0.1`, and the assumption is that `docker stack deploy` drops the bind IP from the short port syntax and publishes on all interfaces via the routing mesh. If that assumption fails, publish the gateway port in host mode (long syntax) or give openresty a `litellm` consumer flag instead.

- Disable/prune path: `provides: litellm_ui` makes `expand_service_tokens('web-app-litellm')` expand to `services.litellm_ui.*`, so disabling the UI role does not clear its `services.litellm` consumer contract; the gateway stays force-loaded until that flag is flipped manually or the expander learns about redirected consumer contracts.

- Persona flows: `PERSONA_ADMINISTRATOR_BLOCKED` / `PERSONA_BIBER_BLOCKED` stay set because the shared persona helper needs a DOM logout control the Control UI does not expose. The administrator's SSO round-trip is covered by `test-oidc-login.js` instead. Unblock the helper once the UI gains a logout affordance.
- SSO user cap: LiteLLM refuses SSO above 5 rows in `litellm_usertable` without `LITELLM_LICENSE` (`litellm/proxy/management_endpoints/ui_sso.py` at `v1.77.3-stable`). Wire a licence variable, or pin the UI to the administrator, before a sixth person needs the UI.
