require "json"
require "uri"

doorkeeper_plaintext_hosts = JSON.parse(ENV.fetch("NC_REDIRECT_BASE_URLS")).filter_map do |url|
  parsed = URI.parse(url)
  parsed.host.downcase if parsed.scheme == "http"
end
doorkeeper_force_ssl = Doorkeeper.config.force_ssl_in_redirect_uri
Doorkeeper.config.instance_variable_set(
  :@force_ssl_in_redirect_uri,
  lambda do |uri|
    return false if doorkeeper_plaintext_hosts.include?(uri.host.to_s.downcase)

    doorkeeper_force_ssl.respond_to?(:call) ? doorkeeper_force_ssl.call(uri) : !!doorkeeper_force_ssl
  end
)
