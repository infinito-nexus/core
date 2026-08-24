# nocheck: mirrored-unit-test - runs in the OpenProject console and writes through
# Setting; the model only exists once OpenProject has booted
require "json"

settings = JSON.parse(ENV.fetch("OPENPROJECT_RAILS_SETTINGS"))
settings.each do |key, value|
  Setting[key.to_sym] = value
end
puts "Applied #{settings.size} OpenProject setting(s)."
