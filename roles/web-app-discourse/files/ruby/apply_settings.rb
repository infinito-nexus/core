require "json"

SiteSetting.force_https = ENV.fetch("DISCOURSE_FORCE_HTTPS") == "true"
second_factor_enforcement = ENV.fetch("DISCOURSE_ENFORCE_SECOND_FACTOR")
SiteSetting.enforce_second_factor = second_factor_enforcement if second_factor_enforcement == "no"
SiteSetting.enable_local_logins = ENV.fetch("DISCOURSE_LOCAL_LOGINS") == "true"
SiteSetting.enable_local_logins_via_email = ENV.fetch("DISCOURSE_LOGIN_EMAIL") == "true"
SiteSetting.enable_passkeys = ENV.fetch("DISCOURSE_LOGIN_PASSKEY") == "true"
SiteSetting.allow_new_registrations = ENV.fetch("DISCOURSE_ALLOW_NEW_REGISTRATIONS") == "true"
SiteSetting.enforce_second_factor = second_factor_enforcement unless second_factor_enforcement == "no"

JSON.parse(ENV.fetch("DISCOURSE_SITE_SETTINGS")).each do |key, value|
  SiteSetting.public_send("#{key}=", value)
end

if ENV.fetch("DISCOURSE_OIDC_ENABLED") == "true"
  SiteSetting.openid_connect_verbose_logging = ENV.fetch("DISCOURSE_OIDC_VERBOSE") == "true"
  SiteSetting.username_change_period = 0

  SiteSetting.openid_connect_discovery_document = ENV.fetch("DISCOURSE_OIDC_DISCOVERY_DOCUMENT")
  SiteSetting.openid_connect_client_id = ENV.fetch("DISCOURSE_OIDC_CLIENT_ID")
  SiteSetting.openid_connect_client_secret = ENV.fetch("DISCOURSE_OIDC_CLIENT_SECRET")
  SiteSetting.openid_connect_enabled = ENV.fetch("DISCOURSE_LOGIN_SSO") == "true"
  SiteSetting.openid_connect_rp_initiated_logout_redirect = ENV.fetch("DISCOURSE_OIDC_LOGOUT_REDIRECT")
  SiteSetting.openid_connect_allow_association_change = false
  SiteSetting.openid_connect_match_by_email = true
  SiteSetting.openid_connect_email_verified_claim_fallback = false
  SiteSetting.openid_connect_rp_initiated_logout = true
  SiteSetting.openid_connect_groups_claim = ENV.fetch("DISCOURSE_OIDC_GROUPS_CLAIM")

  SiteSetting.email_editable = false
  SiteSetting.auth_overrides_email = true
  SiteSetting.auth_overrides_name = true
  SiteSetting.auth_overrides_username = false

  url = SiteSetting.openid_connect_discovery_document.to_s.strip
  host = url.sub(%r{\Ahttps?://}i, "").split("/").first.to_s.strip.split(":").first.to_s.strip
  list = SiteSetting.allowed_internal_hosts.to_s.split("|").map(&:strip).reject(&:empty?)
  if !host.empty? && host =~ /\A[a-z0-9.-]+\z/i && !list.include?(host)
    list << host
    SiteSetting.allowed_internal_hosts = list.join("|")
  end

  Discourse.cache.delete("openid-connect-discovery-#{url}")
end
