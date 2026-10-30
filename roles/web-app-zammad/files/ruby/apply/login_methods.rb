# nocheck: mirrored-unit-test - runs in the Zammad console and writes through
# Setting.set; the model only exists once Zammad has booted
UserInfo.current_user_id = 1

def enabled?(name)
  ENV.fetch(name) == "true"
end

second_factor = enabled?("LOGIN_2FA")

Setting.set("auth_openid_connect", enabled?("LOGIN_SSO"))
Setting.set("user_show_password_login", enabled?("LOGIN_FORM"))
Setting.set("user_create_account", enabled?("LOGIN_REGISTRATION"))
Setting.set("two_factor_authentication_method_authenticator_app", second_factor)
Setting.set("two_factor_authentication_method_security_keys", second_factor)
Setting.set("two_factor_authentication_enforce_role_ids", [])
