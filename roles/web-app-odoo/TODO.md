# TODO

- [Document custom addon development workflow](https://open.project.infinito.nexus/wp/560)
- [Add support for Odoo Enterprise features (if licensed)](https://open.project.infinito.nexus/wp/561)
- [Implement email template customization](https://open.project.infinito.nexus/wp/562)
- [Add custom CSS injection support](https://open.project.infinito.nexus/wp/563)
- [Document upgrade procedures between Odoo versions](https://open.project.infinito.nexus/wp/564)
- `tasks/03_install_modules/module_ops.yml` hands the database password to `odoo` as `--db_password` in argv (lines 11, 34, 53, 72 and 103), where the process list of the container shows it while a module installs. `odoo shell` in `tasks/07_design.yml` connects without the flag, because `ODOO_RC` already names the connection. Options: drop the flag from the five commands, or pass the value through the environment.
- The Discuss app shows `Real-time connection lost...` about 20 seconds after it loads on the local compose stack, with the corporate design switched on and off alike. The browser requests `/bus/websocket_worker_bundle` again every 1.5 seconds, port 8072 answers inside the container, and a bare upgrade request to `/websocket` through the proxy returns `400`. The cause is not measured. Options: record the handshake the shared worker sends and compare it with the `/websocket` location of the vhost, then add a spec that waits for a bus frame.
