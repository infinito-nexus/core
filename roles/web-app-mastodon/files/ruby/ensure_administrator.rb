# frozen_string_literal: true
# nocheck: mirrored-unit-test - runs in `rails runner` against Mastodon's UsernameBlock,
# Account, User and UserRole; the models only exist once the app has booted

username = ENV.fetch("MASTODON_ADMIN_USERNAME")
email = ENV.fetch("MASTODON_ADMIN_EMAIL")
password = ENV.fetch("MASTODON_ADMIN_PASSWORD")

changed = UsernameBlock.where(username: username).delete_all.positive?

account = Account.find_local(username)
if account.nil?
  user = User.new(
    email: email,
    password: password,
    agreement: true,
    role_id: UserRole.find_by!(name: "Owner").id,
    confirmed_at: Time.now.utc,
    bypass_registration_checks: true,
    account: Account.new(username: username)
  )
  user.save!
  user.confirmed_at = nil
  user.mark_email_as_confirmed!
  changed = true
else
  user = account.user || abort("FAILED: the local account #{username} has no user")
end

unless user.valid_password?(password)
  user.update!(password: password, password_confirmation: password)
  changed = true
end

unless user.approved?
  user.approved = true
  user.save!
  changed = true
end

puts(changed ? "changed" : "ok")
