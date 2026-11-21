# frozen_string_literal: true

# Env:
#   MASTODON_SSO_DIRECTORY_USERS: JSON list of {username, email, emailVerified, id}
#     from web-app-keycloak utils/directory_users.yml.
# Prints one "skipped <username>: <reason>" line per local account it leaves
# unbound, then "changed" or "ok".

require "json"

PROVIDER = "openid_connect"

changed = false

JSON.parse(ENV.fetch("MASTODON_SSO_DIRECTORY_USERS")).each do |entry|
  uid = entry.fetch("username")
  user = Account.find_local(uid)&.user
  next if user.nil?

  bound = Identity.where(provider: PROVIDER, user_id: user.id).pluck(:uid)
  next if bound.include?(uid)

  holder = Identity.find_by(provider: PROVIDER, uid: uid)
  reason =
    if entry.fetch("emailVerified") != true
      "the Keycloak email is not verified"
    elsif !user.email.to_s.casecmp?(entry.fetch("email").to_s)
      "the Mastodon email differs from the Keycloak email"
    elsif bound.any?
      "the account is linked to another identity"
    elsif holder && !holder.user_id.nil?
      "the identity is linked to another account"
    end

  if reason
    puts "skipped #{uid}: #{reason}"
    next
  end

  identity = holder || Identity.new(provider: PROVIDER, uid: uid)
  identity.user_id = user.id
  identity.save!
  changed = true
end

puts(changed ? "changed" : "ok")
