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

if ENV.fetch("DISCOURSE_OIDC_ENABLED") == "true"
  puts "oidc_secret_matches=#{SiteSetting.openid_connect_client_secret == ENV.fetch('DISCOURSE_OIDC_CLIENT_SECRET')}"
  puts "oidc_enabled=#{SiteSetting.openid_connect_enabled == true}"
  puts "oidc_host_allowed=#{SiteSetting.allowed_internal_hosts.to_s.split('|').any? { |h| SiteSetting.openid_connect_discovery_document.to_s.include?(h.strip) }}"
  puts "oidc_profile_overridden=#{SiteSetting.auth_overrides_email && SiteSetting.auth_overrides_name && !SiteSetting.email_editable}"
  puts "oidc_groups_claim=#{SiteSetting.openid_connect_groups_claim}"
end
