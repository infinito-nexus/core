# nocheck: mirrored-unit-test - runs in the Decidim console and updates
# Decidim::Organization#host; the model only exists once Rails has booted
org = Decidim::Organization.first
org.host = ENV.fetch("DECIDIM_ORG_HOST")
org.save
puts "Organization host set to: #{org.host}"
