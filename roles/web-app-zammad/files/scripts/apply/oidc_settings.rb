UserInfo.current_user_id = 1

Setting.set("fqdn",      ENV.fetch("ZAMMAD_FQDN"))
Setting.set("http_type", ENV.fetch("ZAMMAD_HTTP_TYPE"))

Setting.set("auth_third_party_auto_link_at_inital_login", true)

Setting.set("auth_openid_connect", true)
Setting.set("auth_openid_connect_credentials", {
  "display_name"                 => ENV.fetch("OIDC_BUTTON_TEXT"),
  "identifier"                   => ENV.fetch("OIDC_CLIENT_ID"),
  "secret"                       => ENV.fetch("OIDC_CLIENT_SECRET"),
  "issuer"                       => ENV.fetch("OIDC_ISSUER_URL"),
  "scope"                        => "openid email profile",
  "uid_field"                    => "preferred_username",
  "send_scope_to_token_endpoint" => true,
})
