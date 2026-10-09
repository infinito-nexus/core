# Todos

- Optimize buffering
- Optimize caching
- Make 'proxy_hide_header Content-Security-Policy' optional by using more_header option.
- Refactor this role - It seems like it's just an wrapper for 'sys-svc-webserver-https' which doesn't add any additional logic
- Compressed upstream bodies: `templates/location/html.conf.j2` sends `Accept-Encoding: ""` so that the body filter of `sys-front-inj-all` (`body_filter_by_lua_file` in `templates/location.lua.j2`) reads plain HTML. An upstream that compresses regardless passes the filter unchanged, and no snippet (design, tracking, logout) reaches that page. Measured on `web-app-stalwart`: `/login` answers `Content-Encoding: gzip` for `Accept-Encoding: identity`. Inflate such bodies before the filter runs, or inject through a hook that does not read the body.
