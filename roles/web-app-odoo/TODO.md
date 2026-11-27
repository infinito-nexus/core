# TODO

- [Document custom addon development workflow](https://open.project.infinito.nexus/wp/560)
- [Add support for Odoo Enterprise features (if licensed)](https://open.project.infinito.nexus/wp/561)
- [Implement email template customization](https://open.project.infinito.nexus/wp/562)
- [Add custom CSS injection support](https://open.project.infinito.nexus/wp/563)
- [Document upgrade procedures between Odoo versions](https://open.project.infinito.nexus/wp/564)
- The role runs Odoo 20.0 (`meta/services.yml`), and `files/pip/requirements-no-deps.txt` builds `fs_storage`, `fs_attachment` and `fs_attachment_s3` from the head commits of the open OCA 20.0 migrations [#670](https://github.com/OCA/storage/pull/670), [#679](https://github.com/OCA/storage/pull/679) and [#686](https://github.com/OCA/storage/pull/686). Once OCA publishes installable 20.x releases of the three modules on PyPI, pin those instead.
- The Discuss app shows `Real-time connection lost...` about 20 seconds after it loads on the local compose stack, with the corporate design switched on and off alike. The browser requests `/bus/websocket_worker_bundle` again every 1.5 seconds, port 8072 answers inside the container, and a bare upgrade request to `/websocket` through the proxy returns `400`. The cause is not measured. Options: record the handshake the shared worker sends and compare it with the `/websocket` location of the vhost, then add a spec that waits for a bus frame.
