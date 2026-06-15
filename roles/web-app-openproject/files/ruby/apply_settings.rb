require "json"

settings = JSON.parse(ENV.fetch("OPENPROJECT_RAILS_SETTINGS"))
settings.each do |key, value|
  Setting[key.to_sym] = value
end
puts "Applied #{settings.size} OpenProject setting(s)."
