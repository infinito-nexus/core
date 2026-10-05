# TODO

- MCP task secrets: `tasks/utils/mcp/provision.yml` and `tasks/utils/mcp/realign_owner.yml` hand `HA_PASSWORD` and `HA_SERVICE_PASSWORD` to `container exec` with `-e`, `realign_owner.yml` passes the owner password as an argument of `hass --script auth`, and `tasks/utils/mcp/probe.yml` passes `HA_TOKEN` with `-e`, so each value is part of the task command. Feed them on standard input the way `tasks/utils/owner/provision.yml` and `tasks/utils/owner/realign.yml` do.
- Script name: `files/python/provision_mcp.py` also provisions the owner since `tasks/utils/owner/provision.yml` runs it with `HA_OWNER_ONLY=1`. Rename it to a name that covers both uses.
- Product name: the sidebar title, the `alt` text of the sign-in logo, the web app manifest (`name`, icons) and the launch screen logo still show Home Assistant; the frontend offers no setting for them, and the theme and the sign-in stylesheet do not reach them.
- Sign-in stylesheet: `templates/style.css.j2` repeats the `--wa-color-*` assignments Home Assistant derives on `html`, because the sign-in page takes no theme. Compare the list with the frontend when the image version moves.
