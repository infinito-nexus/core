# Todos

- Gravatar is on (`gravatar_enabled` returns `true`): the top bar avatar loads from `https://secure.gravatar.com/avatar/<hash>` (measured `naturalWidth` 80 from the Playwright container), so avatars break on an offline host and every page view sends the e-mail hash to a third party. Options: `gravatar: enabled: false` in `templates/config/gitlab.yml.j2` (fresh installs), or converge the application setting `gravatar_enabled`.
- The README section "MCP server" names `v19.3.1` and a token on `root`; `meta/services.yml` pins a newer release and `tasks/utils/mcp/provision.yml` mints the token on `mcp-web-app-gitlab`.
