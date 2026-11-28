# nocheck: mirrored-unit-test - runs in the Decidim console and writes through
# Decidim::Organization; the model is unavailable outside the container
#
# Env:
#   DECIDIM_OIDC_LOGIN_ENABLED: "true" shows the OpenID Connect entry on the sign-in page.
org = Decidim::Organization.first
settings = org.omniauth_settings || {}
settings["omniauth_settings_openid_connect_enabled"] = ENV.fetch("DECIDIM_OIDC_LOGIN_ENABLED") == "true"
org.omniauth_settings = settings
org.save!
puts "OIDC settings configured"
