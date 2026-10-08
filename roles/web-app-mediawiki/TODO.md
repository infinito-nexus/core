# TODO

- Discourse SSO: `meta/addons/DiscourseSsoConsumer.yml` stands at `enabled: false`. Every tag the project publishes requires `PluggableAuth: ~6.3`, 5.0.2 and the newest, 6.0.0, alike, while `MEDIAWIKI_EXT_BRANCH` resolves PluggableAuth to `REL1_46`, which carries 7.5.0; 6.0.0 additionally declares `php >= 8.4` against the image's 8.3.35. `update.monitored` stays on, so re-enable the addon and restore the `services.discourse.enabled and services.sso.enabled` gate once a release declares PluggableAuth 7.
