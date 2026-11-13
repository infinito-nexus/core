# frozen_string_literal: true
# nocheck: mirrored-unit-test - runs in `rails runner` against Greenlight's SiteSetting model; the constants only exist once the app has booted

# Environment:
#   MODE: "read" prints the stored RegistrationMethod and whether "converge" would change it, as one JSON line, and writes nothing; "converge" writes it
#   REGISTRATION_METHOD: the key of SiteSetting::REGISTRATION_METHODS the setting converges on

require "json"

PROVIDER = "greenlight"
MODES = %w[read converge].freeze

mode = ENV.fetch("MODE")
abort("MODE must be one of #{MODES.join(', ')}") unless MODES.include?(mode)

wanted = SiteSetting::REGISTRATION_METHODS.fetch(ENV.fetch("REGISTRATION_METHOD").to_sym)
setting = SiteSetting.joins(:setting).find_by!(provider: PROVIDER, setting: { name: "RegistrationMethod" })

if mode == "read"
  puts JSON.generate({ registration_method: setting.value, pending: setting.value != wanted })
elsif setting.value == wanted
  puts "NOOP RegistrationMethod=#{wanted}"
else
  setting.update!(value: wanted)
  puts "CHANGED RegistrationMethod=#{wanted}"
end
