# nocheck: mirrored-unit-test - runs in the Zammad console against
# Doorkeeper::Application; the model only exists once Zammad has booted
base = ENV.fetch("NC_BASE_URL").sub(%r{/\z}, "")
path = ENV.fetch("NC_REDIRECT_PATH")
redirect_uris = ["#{base}#{path}", "#{base}/index.php#{path}"].join("\n")

app = Doorkeeper::Application.find_or_initialize_by(name: "Nextcloud")
was_new = app.new_record?
app.redirect_uri = redirect_uris
app.scopes = "full" if app.respond_to?(:scopes=)
app.confidential = true if app.respond_to?(:confidential=)
app.save!

secret = nil
if was_new
  secret = (app.plaintext_secret rescue nil)
elsif ENV["NC_HAS_SECRET"].to_s.strip.empty? && app.respond_to?(:renew_secret)
  app.renew_secret
  app.save!
  secret = (app.plaintext_secret rescue nil)
end

puts "CLIENT_ID=#{app.uid}"
puts "CLIENT_SECRET=#{secret}" unless secret.to_s.empty?
