# Todo

- Enable Whatsapp by default
- Enable Telegram by default
- Enable Slack by default
- Enable ChatGPT by default
- The MDAD bootstrap wait in `tasks/flavor/ansible/05_proxy_wiring.yml` (line 7 to 14) is nearly exhausted: a cold bootstrap took about 24 minutes in a compose baseline of 2026-10-09 and used 287 of its 360 retries at 5 s, while the task name still says "cold ~10-15min"; options: raise `retries` to about twice the measured time (about 580) and name the measured duration.
- `tasks/flavor/ansible/05_proxy_wiring.yml` (line 92) passes `MATRIX_ADMINISTRATOR_PASSWORD` in argv of `register_new_matrix_user -p`, so the `-vv` deploy log prints it whenever `MASK_CREDENTIALS_IN_LOGS` is off; options: forward it with `container exec -e NAME` plus the task's `environment:` and read it inside the Synapse container from that variable or from stdin through `--password-file`.
