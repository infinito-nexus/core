# frozen_string_literal: true
# nocheck: mirrored-unit-test - runs in `rails runner` against Mastodon's
# live Account and Devise models; nothing here is callable in isolation

username = ENV.fetch("MASTODON_ADMIN_USERNAME")
password = ENV.fetch("MASTODON_ADMIN_PASSWORD")
user = Account.find_local!(username).user
if user.valid_password?(password)
  puts "PASSWORD_UNCHANGED"
else
  user.update!(password: password, password_confirmation: password)
  puts "PASSWORD_CHANGED"
end
