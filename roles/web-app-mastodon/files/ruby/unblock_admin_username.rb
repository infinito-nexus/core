# frozen_string_literal: true
# nocheck: mirrored-unit-test - runs in `rails runner` and deletes from Mastodon's
# UsernameBlock; the model only exists once the app has booted

username = ENV.fetch("MASTODON_ADMIN_USERNAME")
deleted = UsernameBlock.where(username: username).delete_all
puts "Unblocked #{deleted} username block(s) for #{username}"
