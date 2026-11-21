# nocheck: mirrored-unit-test - runs in the Zammad console and writes through
# Setting.set; the model only exists once Zammad has booted
UserInfo.current_user_id = 1

Setting.set("fqdn",      ENV.fetch("ZAMMAD_FQDN"))
Setting.set("http_type", ENV.fetch("ZAMMAD_HTTP_TYPE"))

Setting.set("auth_third_party_auto_link_at_inital_login", false)

Setting.set("auth_openid_connect_credentials", {
  "display_name"                 => ENV.fetch("OIDC_BUTTON_TEXT"),
  "identifier"                   => ENV.fetch("OIDC_CLIENT_ID"),
  "issuer"                       => ENV.fetch("OIDC_ISSUER_URL"),
  "scope"                        => ENV.fetch("OIDC_SCOPE"),
  "uid_field"                    => ENV.fetch("OIDC_UID_FIELD"),
  "pkce"                         => true,
  "send_scope_to_token_endpoint" => true,
})

admin = User.find_by(login: ENV.fetch("OIDC_ADMIN_LOGIN").downcase)
if admin
  authorization = Authorization.find_or_initialize_by(provider: "openid_connect", uid: admin.login)
  unless authorization.user_id == admin.id
    authorization.user_id  = admin.id
    authorization.username = admin.login
    authorization.save!
  end
end
