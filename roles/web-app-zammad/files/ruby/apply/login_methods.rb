# nocheck: mirrored-unit-test - runs in the Zammad console and writes through
# Setting.set; the model only exists once Zammad has booted
require "json"

UserInfo.current_user_id = 1

def enabled?(name)
  ENV.fetch(name) == "true"
end

second_factor = enabled?("LOGIN_2FA")

JSON.parse(ENV.fetch("ZAMMAD_SECURITY")).each { |name, value| Setting.set(name, value) }
Setting.set("two_factor_authentication_method_authenticator_app", second_factor)
Setting.set("two_factor_authentication_method_security_keys", second_factor)
Setting.set(
  "two_factor_authentication_enforce_role_ids",
  enabled?("LOGIN_2FA_ENFORCED") ? Role.where(active: true).pluck(:id).sort : []
)
