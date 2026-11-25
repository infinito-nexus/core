# nocheck: mirrored-unit-test - runs in Mastodon's `rails runner` against its live Doorkeeper tables; the models exist only inside the booted app
# Args (environment):
#   CROSSPOSTER_ACCOUNT: local Mastodon username that grants the code.
#   CROSSPOSTER_AUTHORIZE: authorization URL OpenPost started; its query names the client, redirect URI, scope and PKCE challenge.
# Prints CROSSPOSTER_GRANT=<authorization code>.
query = Rack::Utils.parse_query(URI.parse(ENV.fetch("CROSSPOSTER_AUTHORIZE")).query)
account = Account.find_local!(ENV.fetch("CROSSPOSTER_ACCOUNT"))
application = Doorkeeper::Application.find_by!(uid: query.fetch("client_id"))
grant = Doorkeeper::AccessGrant.create!(
  application: application,
  resource_owner_id: account.user.id,
  redirect_uri: query.fetch("redirect_uri"),
  scopes: query.fetch("scope", application.scopes.to_s),
  code_challenge: query["code_challenge"],
  code_challenge_method: query["code_challenge_method"],
  expires_in: 600
)
puts "CROSSPOSTER_GRANT=#{grant.plaintext_token}"
