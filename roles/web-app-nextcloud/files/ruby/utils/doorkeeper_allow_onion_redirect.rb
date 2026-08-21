# nocheck: mirrored-unit-test - reconfigures Doorkeeper's force_ssl_in_redirect_uri on
# the live config object; there is no Doorkeeper to configure outside the app
previous = Doorkeeper.config.force_ssl_in_redirect_uri
Doorkeeper.config.instance_variable_set(
  :@force_ssl_in_redirect_uri,
  lambda do |uri|
    return false if uri.host.to_s.downcase.end_with?(".onion")

    previous.respond_to?(:call) ? previous.call(uri) : !!previous
  end
)
