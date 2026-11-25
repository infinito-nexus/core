# nocheck: mirrored-unit-test - runs in Mastodon's `rails runner` against its live Doorkeeper tables; the models exist only inside the booted app
# Args (environment):
#   CROSSPOSTER_ACCOUNT: local Mastodon username the token belongs to.
# Prints CROSSPOSTER_TOKEN=<access token>.
account = Account.find_local!(ENV.fetch("CROSSPOSTER_ACCOUNT"))
application = Doorkeeper::Application.find_or_create_by!(name: "Crossposter CI") do |created|
  created.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
  created.scopes = "read write"
end
token = Doorkeeper::AccessToken.create!(application: application, resource_owner_id: account.user.id, scopes: "read write")
puts "CROSSPOSTER_TOKEN=#{token.plaintext_token}"
