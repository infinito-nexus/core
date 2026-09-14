# nocheck: mirrored-unit-test - runs in the Discourse console against SiteSetting and
# Discourse.cache; both only exist once the application has booted

require "json"

SiteSetting.force_https = ENV.fetch("DISCOURSE_FORCE_HTTPS") == "true"
SiteSetting.enable_local_logins = ENV.fetch("DISCOURSE_LOCAL_LOGINS") == "true"

JSON.parse(ENV.fetch("DISCOURSE_LDAP_SITE_SETTINGS")).each do |key, value|
  SiteSetting.public_send("#{key}=", value)
end

if ENV.fetch("DISCOURSE_OIDC_ENABLED") == "true"
  SiteSetting.openid_connect_verbose_logging = ENV.fetch("DISCOURSE_OIDC_VERBOSE") == "true"
  SiteSetting.enable_passkeys = false
  SiteSetting.username_change_period = 0

  SiteSetting.openid_connect_discovery_document = ENV.fetch("DISCOURSE_OIDC_DISCOVERY_DOCUMENT")
  SiteSetting.openid_connect_client_id = ENV.fetch("DISCOURSE_OIDC_CLIENT_ID")
  SiteSetting.openid_connect_client_secret = ENV.fetch("DISCOURSE_OIDC_CLIENT_SECRET")
  SiteSetting.openid_connect_enabled = true
  SiteSetting.openid_connect_rp_initiated_logout_redirect = ENV.fetch("DISCOURSE_OIDC_LOGOUT_REDIRECT")
  SiteSetting.openid_connect_allow_association_change = false
  SiteSetting.openid_connect_rp_initiated_logout = true

  url = SiteSetting.openid_connect_discovery_document.to_s.strip
  host = url.sub(%r{\Ahttps?://}i, "").split("/").first.to_s.strip.split(":").first.to_s.strip
  list = SiteSetting.allowed_internal_hosts.to_s.split("|").map(&:strip).reject(&:empty?)
  if !host.empty? && host =~ /\A[a-z0-9.-]+\z/i && !list.include?(host)
    list << host
    SiteSetting.allowed_internal_hosts = list.join("|")
  end

  Discourse.cache.delete("openid-connect-discovery-#{url}")
end
