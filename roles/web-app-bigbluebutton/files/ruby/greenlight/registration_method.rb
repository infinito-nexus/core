# frozen_string_literal: true
# nocheck: mirrored-unit-test - runs in `rails runner` against Greenlight's SiteSetting model; the constants only exist once the app has booted

PROVIDER = "greenlight"

wanted = SiteSetting::REGISTRATION_METHODS.fetch(ENV.fetch("REGISTRATION_METHOD").to_sym)
setting = SiteSetting.joins(:setting).find_by!(provider: PROVIDER, setting: { name: "RegistrationMethod" })

if setting.value == wanted
  puts "NOOP RegistrationMethod=#{wanted}"
else
  setting.update!(value: wanted)
  puts "CHANGED RegistrationMethod=#{wanted}"
end
