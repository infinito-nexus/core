# nocheck: mirrored-unit-test - runs in the Decidim console against Decidim::Organization; the model only exists once Rails has booted
#
# Env:
#   DECIDIM_USERS_REGISTRATION_MODE: enabled (sign-in and sign-up), existing (sign-in only) or disabled (external accounts only).
organization = Decidim::Organization.first
mode = ENV.fetch("DECIDIM_USERS_REGISTRATION_MODE")
if organization.users_registration_mode == mode
  puts "Registration mode kept: #{mode}"
else
  organization.update!(users_registration_mode: mode)
  puts "Registration mode set to #{mode}"
end
