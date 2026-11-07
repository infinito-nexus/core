# nocheck: mirrored-unit-test - reads SiteSetting and User out of the booted
# application, neither of which exists outside the Discourse console

SiteSetting.refresh!

email = ENV.fetch("DISCOURSE_ADMIN_EMAIL")
password = ENV.fetch("DISCOURSE_ADMIN_PASSWORD")

user = User.find_by_email(email)
puts "administrator_present=#{!user.nil?}"
puts "administrator_admin=#{user&.admin == true}"
puts "administrator_active=#{user&.active == true}"
puts "administrator_password_matches=#{user&.confirm_password?(password) == true}"

login_methods = {
  enable_local_logins: "DISCOURSE_LOCAL_LOGINS",
  enable_local_logins_via_email: "DISCOURSE_LOGIN_EMAIL",
  enable_passkeys: "DISCOURSE_LOGIN_PASSKEY",
  allow_new_registrations: "DISCOURSE_ALLOW_NEW_REGISTRATIONS",
}
puts "login_methods_applied=#{login_methods.all? { |setting, env| SiteSetting.public_send(setting) == (ENV.fetch(env) == 'true') }}"

enforcement = ENV.fetch("DISCOURSE_ENFORCE_SECOND_FACTOR")
puts "second_factor_enforcement_applied=#{SiteSetting.enforce_second_factor.to_s == enforcement}"

if ENV.fetch("DISCOURSE_OIDC_ENABLED") == "true"
  puts "oidc_secret_matches=#{SiteSetting.openid_connect_client_secret == ENV.fetch('DISCOURSE_OIDC_CLIENT_SECRET')}"
  puts "oidc_enabled=#{SiteSetting.openid_connect_enabled == (ENV.fetch('DISCOURSE_LOGIN_SSO') == 'true')}"
  puts "oidc_host_allowed=#{SiteSetting.allowed_internal_hosts.to_s.split('|').any? { |h| SiteSetting.openid_connect_discovery_document.to_s.include?(h.strip) }}"
  puts "oidc_profile_overridden=#{SiteSetting.auth_overrides_email && SiteSetting.auth_overrides_name && !SiteSetting.email_editable}"
  puts "oidc_groups_claim=#{SiteSetting.openid_connect_groups_claim}"
end
