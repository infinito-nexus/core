# frozen_string_literal: true
# nocheck: mirrored-unit-test - runs in `rails runner` against Mastodon's Setting model,
# which only exists once the app has booted

mode = ENV.fetch("MASTODON_REGISTRATIONS_MODE")

if Setting.registrations_mode == mode
  puts "ok"
else
  Setting.registrations_mode = mode
  puts "changed"
end
