# Todos

- `FLOWISE_USERNAME` and `FLOWISE_PASSWORD` in `templates/env.j2` are read by no Flowise 3.1.4 code path (absent from `server-commands-base.ts` and `.env.example`; measured in the container: no file under `node_modules/flowise/dist` or `flowise-components/dist` names either key, while `FLOWISE_SECRETKEY_OVERWRITE` appears 8 times), so they create no account and only put the administrator password into the container environment; the instance account is `flowise-api-bot`, registered by `tasks/utils/owner.yml`. Option: drop both keys.
