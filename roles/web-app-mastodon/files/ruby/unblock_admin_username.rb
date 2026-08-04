# frozen_string_literal: true

username = ENV.fetch("MASTODON_ADMIN_USERNAME")
deleted = UsernameBlock.where(username: username).delete_all
puts "Unblocked #{deleted} username block(s) for #{username}"
