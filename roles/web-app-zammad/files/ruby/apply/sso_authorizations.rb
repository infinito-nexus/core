# frozen_string_literal: true

# Env:
#   ZAMMAD_SSO_DIRECTORY_USERS: JSON list of {username, email, emailVerified, id}
#     from web-app-keycloak utils/directory_users.yml.
# Prints one "skipped <login>: <reason>" line per local account it leaves
# unbound, then "changed" or "ok".

require "json"

PROVIDER = "openid_connect"

UserInfo.current_user_id = 1
changed = false

JSON.parse(ENV.fetch("ZAMMAD_SSO_DIRECTORY_USERS")).each do |entry|
  uid = entry.fetch("username").downcase
  user = User.find_by(login: uid)
  next if user.nil?

  bound = Authorization.where(provider: PROVIDER, user_id: user.id).pluck(:uid)
  next if bound.include?(uid)

  reason =
    if entry.fetch("emailVerified") != true
      "the Keycloak email is not verified"
    elsif !user.email.to_s.casecmp?(entry.fetch("email").to_s)
      "the Zammad email differs from the Keycloak email"
    elsif bound.any?
      "the account is linked to another identity"
    elsif Authorization.find_by(provider: PROVIDER, uid: uid)
      "the identity is linked to another account"
    end

  if reason
    puts "skipped #{uid}: #{reason}"
    next
  end

  Authorization.create!(provider: PROVIDER, uid: uid, username: uid, user_id: user.id)
  changed = true
end

puts(changed ? "changed" : "ok")
