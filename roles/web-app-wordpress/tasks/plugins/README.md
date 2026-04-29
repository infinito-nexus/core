# WordPress Plugins

This WordPress setup integrates several powerful plugins to extend functionality with authentication, federation, and external discussion platforms:

## OpenID Connect Generic Client 🔐
Enables secure login via OpenID Connect (OIDC).  
Plugin used: [daggerhart-openid-connect-generic](https://wordpress.org/plugins/daggerhart-openid-connect-generic/)

## WP Discourse 💬
Seamlessly connects WordPress with a Discourse forum for comments, discussions, and single sign-on (SSO).  
Plugin used: [wp-discourse](https://wordpress.org/plugins/wp-discourse/).
Runtime contract for the WordPress to Discourse post round-trip (published post MUST appear as a Discourse topic) is defined in [007-wordpress-discourse-post-round-trip.md](../../../../docs/requirements/007-wordpress-discourse-post-round-trip.md).

## ActivityPub 🌍
Federates your blog with the Fediverse, making it accessible on platforms like Mastodon and Friendica.  
Plugin used: [activitypub](https://wordpress.org/plugins/activitypub/)
