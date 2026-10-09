# WordPress Plugins

This WordPress setup integrates several powerful plugins to extend functionality with authentication, federation, and external discussion platforms:

## OpenID Connect Generic Client 🔐

Enables secure login via OpenID Connect (OIDC).  
Plugin used: [daggerhart-openid-connect-generic](https://wordpress.org/plugins/daggerhart-openid-connect-generic/)

## WP Discourse 💬

Seamlessly connects WordPress with a Discourse forum for comments, discussions, and single sign-on (SSO).  
Plugin used: [wp-discourse](https://wordpress.org/plugins/wp-discourse/).
Runtime contract for the WordPress to Discourse post round-trip: a published post MUST appear as a Discourse topic.

## ActivityPub 🌍

Federates your blog with the Fediverse, making it accessible on platforms like Mastodon and Friendica.  
Plugin used: [activitypub](https://wordpress.org/plugins/activitypub/)

## Video Conferencing with BBB 🎥

Publishes BigBlueButton rooms as WordPress content. Enabled with the `bigbluebutton` service, bridges it, and reads the partner API URL and shared secret from the addon config.  
Plugin used: [video-conferencing-with-bbb](https://wordpress.org/plugins/video-conferencing-with-bbb/)

## Listmonk Integration 📧

Posts WordPress subscriptions to the Listmonk API. Enabled with the `listmonk` service and bridges it; the API user is created in Listmonk and entered in the plugin.  
Plugin used: [integration-for-listmonk-mailing-list-and-newsletter-manager](https://wordpress.org/plugins/integration-for-listmonk-mailing-list-and-newsletter-manager/)

## Video Manager for PeerTube 📺

Lists and embeds videos of the partner PeerTube instance. Enabled with the `peertube` service and bridges it, reading the instance URL from the addon config.  
Plugin used: [video-manager-for-peertube](https://wordpress.org/plugins/video-manager-for-peertube/)
