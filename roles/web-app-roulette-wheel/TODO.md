# Todos

- The `roulette-wheel` container idles at 238.1 MiB of its 265 MiB `mem_limit` (89.9 %, 0 restarts, not OOM-killed, measured with `docker stats` after the baseline deploy): `npm run start` serves the page through `webpack-dev-server` in development mode with `ts-loader`, although the page only loads the production bundle `scripts/bundle.js` that `npm run build` already wrote. Options: serve the built `dist/` statically (a static file server stage in `files/Dockerfile`), or raise `mem_limit` in `meta/services.yml`.
